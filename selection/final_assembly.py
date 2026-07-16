from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd


class FinalCandidateAssembler:
    """
    Final Assembly v1.

    Responsibilities:
    - hard gate on survival / capacity / cycle participation
    - preserve cycle-reaction evidence as the primary selection signal
    - preserve Quant Quality as secondary evidence, not a hard filter
    - reserve Research / Moat fields for a future module

    This layer intentionally does NOT pretend moat or valuation research exists.
    """

    HARD_BAD_SURVIVAL = {"FAIL", "DEAD", "DISTRESSED", "UNSAFE"}
    HARD_BAD_CAPACITY = {"CAPACITY_DESTROYED", "CAPACITY_EXITED", "CORE_ASSETS_SOLD"}
    HARD_BAD_PARTICIPATION = {"LOST", "EXITED", "NOT_PARTICIPATING"}

    def __init__(self, top_n_per_theme: int = 10):
        self.top_n_per_theme = top_n_per_theme

    @staticmethod
    def _pct_rank(s: pd.Series, higher_is_better: bool = True) -> pd.Series:
        x = pd.to_numeric(s, errors="coerce")
        return x.rank(pct=True, method="average", ascending=higher_is_better) * 100.0

    @staticmethod
    def _find_col(df: pd.DataFrame, names: list[str]) -> str | None:
        for name in names:
            if name in df.columns:
                return name
        return None

    def _build_reaction_score(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()

        existing_score = self._find_col(
            out,
            [
                "cycle_reaction_score",
                "reaction_score",
                "cycle_response_score",
                "explosiveness_score",
            ],
        )
        existing_rank = self._find_col(
            out,
            [
                "cycle_reaction_rank",
                "reaction_rank",
                "cycle_response_rank",
                "explosiveness_rank",
            ],
        )

        if existing_score:
            out["cycle_reaction_score_final"] = pd.to_numeric(
                out[existing_score], errors="coerce"
            )
            out["reaction_score_source"] = existing_score
        else:
            upside_col = self._find_col(
                out, ["upside_elasticity", "up_elasticity", "upside_beta"]
            )
            convexity_col = self._find_col(
                out, ["cycle_convexity", "convexity"]
            )

            components = []
            if upside_col:
                out["_upside_pct"] = (
                    out.groupby("theme")[upside_col]
                    .transform(lambda s: self._pct_rank(s, higher_is_better=True))
                )
                components.append("_upside_pct")

            if convexity_col:
                out["_convexity_pct"] = (
                    out.groupby("theme")[convexity_col]
                    .transform(lambda s: self._pct_rank(s, higher_is_better=True))
                )
                components.append("_convexity_pct")

            if components:
                out["cycle_reaction_score_final"] = out[components].mean(axis=1)
                out["reaction_score_source"] = "+".join(components)
            else:
                # Similarity is only a fallback. It is not the preferred reaction signal.
                similarity_col = self._find_col(
                    out, ["theme_similarity", "corr", "correlation"]
                )
                if similarity_col:
                    out["cycle_reaction_score_final"] = (
                        out.groupby("theme")[similarity_col]
                        .transform(lambda s: self._pct_rank(s, higher_is_better=True))
                    )
                    out["reaction_score_source"] = f"FALLBACK:{similarity_col}"
                else:
                    out["cycle_reaction_score_final"] = np.nan
                    out["reaction_score_source"] = "MISSING"

        if existing_rank:
            out["cycle_reaction_rank_final"] = pd.to_numeric(
                out[existing_rank], errors="coerce"
            )
        else:
            out["cycle_reaction_rank_final"] = (
                out.groupby("theme")["cycle_reaction_score_final"]
                .rank(method="dense", ascending=False)
            )

        return out

    def assemble(
        self,
        reaction: pd.DataFrame,
        quality: pd.DataFrame,
    ) -> pd.DataFrame:
        reaction = self._build_reaction_score(reaction)

        quality_keep = [
            "theme",
            "ts_code",
            "decision_date",
            "capacity_status",
            "survival_status",
            "cycle_participation",
            "fundamental_direction",
            "direction_score",
            "quant_quality_score",
            "quant_quality_rank",
            "quality_evidence",
            "quality_flags",
        ]
        quality_keep = [c for c in quality_keep if c in quality.columns]

        base = reaction.merge(
            quality[quality_keep],
            on=["theme", "ts_code"],
            how="inner",
            suffixes=("", "_quality"),
            validate="one_to_one",
        )

        survival = base.get(
            "survival_status", pd.Series("UNKNOWN", index=base.index)
        ).fillna("UNKNOWN").astype(str).str.upper()
        capacity = base.get(
            "capacity_status", pd.Series("UNKNOWN", index=base.index)
        ).fillna("UNKNOWN").astype(str).str.upper()
        participation = base.get(
            "cycle_participation", pd.Series("UNKNOWN", index=base.index)
        ).fillna("UNKNOWN").astype(str).str.upper()

        base["hard_gate_pass"] = (
            ~survival.isin(self.HARD_BAD_SURVIVAL)
            & ~capacity.isin(self.HARD_BAD_CAPACITY)
            & ~participation.isin(self.HARD_BAD_PARTICIPATION)
        )

        base["research_status"] = "NOT_STARTED"
        base["moat_score"] = np.nan
        base["valuation_status"] = "NOT_STARTED"
        base["valuation_score"] = np.nan

        # No fake final weighted score yet:
        # moat and valuation are intentionally absent.
        # Rank is lexicographic: reaction first, Quant Quality second.
        eligible = base[base["hard_gate_pass"]].copy()
        eligible["assembly_rank"] = (
            eligible.sort_values(
                [
                    "theme",
                    "cycle_reaction_rank_final",
                    "quant_quality_rank",
                    "quant_quality_score",
                ],
                ascending=[True, True, True, False],
                na_position="last",
            )
            .groupby("theme")
            .cumcount()
            .add(1)
        )

        base = base.merge(
            eligible[["theme", "ts_code", "assembly_rank"]],
            on=["theme", "ts_code"],
            how="left",
            validate="one_to_one",
        )

        base["final_bucket"] = "GATED_OUT"
        base.loc[
            base["hard_gate_pass"] & (base["assembly_rank"] <= self.top_n_per_theme),
            "final_bucket",
        ] = "FINAL_CANDIDATE"
        base.loc[
            base["hard_gate_pass"] & (base["assembly_rank"] > self.top_n_per_theme),
            "final_bucket",
        ] = "RESERVE"

        sort_cols = ["theme", "hard_gate_pass", "assembly_rank"]
        base = base.sort_values(
            sort_cols,
            ascending=[True, False, True],
            na_position="last",
        )

        drop_cols = [c for c in base.columns if c.startswith("_")]
        return base.drop(columns=drop_cols, errors="ignore")
