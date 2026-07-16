from __future__ import annotations

from pathlib import Path
import pandas as pd

from selection.survival_advantage import SurvivalAdvantageScorer


class CandidatePoolBuilder:
    """
    Combine:
    1. Quant theme candidates from correlation screening
    2. Manual high-conviction candidates
    3. Survival advantage review scores

    Output:
        data/processed/selection/final_candidate_pool.csv
    """

    def __init__(
        self,
        quant_candidates_path: str | Path = "data/processed/research/theme_candidates.csv",
        manual_candidates_path: str | Path = "config/manual_candidates.csv",
        security_master_path: str | Path = "data/processed/metadata/security_master.csv",
        survival_review_path: str | Path = "config/survival_advantage_template.csv",
        output_dir: str | Path = "data/processed/selection",
    ):
        self.quant_candidates_path = Path(quant_candidates_path)
        self.manual_candidates_path = Path(manual_candidates_path)
        self.security_master_path = Path(security_master_path)
        self.survival_review_path = Path(survival_review_path)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _load_quant_candidates(self) -> pd.DataFrame:
        if not self.quant_candidates_path.exists():
            return pd.DataFrame(columns=["ts_code", "theme", "theme_similarity", "n_obs"])

        df = pd.read_csv(self.quant_candidates_path)
        df["source_quant"] = True
        return df

    def _load_manual_candidates(self) -> pd.DataFrame:
        if not self.manual_candidates_path.exists():
            return pd.DataFrame(columns=["ts_code", "name", "theme", "reason"])

        df = pd.read_csv(self.manual_candidates_path)
        df["source_manual"] = True
        return df

    def _load_security_master(self) -> pd.DataFrame:
        if not self.security_master_path.exists():
            return pd.DataFrame(columns=["ts_code", "name", "industry", "market"])

        sm = pd.read_csv(self.security_master_path)
        keep = [
            c for c in ["ts_code", "name", "industry", "market", "list_date", "list_status"]
            if c in sm.columns
        ]
        return sm[keep].drop_duplicates("ts_code")

    def build(self) -> pd.DataFrame:
        quant = self._load_quant_candidates()
        manual = self._load_manual_candidates()
        security = self._load_security_master()

        if "theme_similarity" not in quant.columns:
            quant["theme_similarity"] = pd.NA
        if "n_obs" not in quant.columns:
            quant["n_obs"] = pd.NA
        if "reason" not in quant.columns:
            quant["reason"] = pd.NA

        if "theme_similarity" not in manual.columns:
            manual["theme_similarity"] = pd.NA
        if "n_obs" not in manual.columns:
            manual["n_obs"] = pd.NA
        if "source_quant" not in manual.columns:
            manual["source_quant"] = False
        if "source_manual" not in quant.columns:
            quant["source_manual"] = False

        combined = pd.concat([quant, manual], ignore_index=True, sort=False)

        if combined.empty:
            return combined

        combined["source_quant"] = combined["source_quant"].fillna(False).astype(bool)
        combined["source_manual"] = combined["source_manual"].fillna(False).astype(bool)

        combined = (
            combined.groupby(["ts_code", "theme"], as_index=False)
            .agg(
                {
                    "theme_similarity": "max",
                    "n_obs": "max",
                    "source_quant": "max",
                    "source_manual": "max",
                    "reason": lambda x: "; ".join([str(v) for v in x.dropna().unique()]),
                }
            )
        )

        combined = combined.merge(security, on="ts_code", how="left")

        survival = SurvivalAdvantageScorer(self.survival_review_path).score()
        survival_keep = [
            c for c in [
                "ts_code",
                "theme",
                "survival_advantage_score",
                "technology_leadership",
                "market_share_trend",
                "cost_curve_position",
                "rd_persistence",
                "balance_sheet_buffer",
                "capacity_survival",
                "management_quality",
                "notes",
            ]
            if c in survival.columns
        ]

        combined = combined.merge(
            survival[survival_keep],
            on=["ts_code", "theme"],
            how="left",
        )

        combined["survival_advantage_score"] = combined["survival_advantage_score"].fillna(0.0)
        combined["theme_similarity"] = pd.to_numeric(combined["theme_similarity"], errors="coerce")

        combined["candidate_priority_score"] = (
            combined["theme_similarity"].fillna(0) * 0.35
            + combined["survival_advantage_score"] * 0.65
        )

        combined = (
            combined.sort_values(
                ["theme", "candidate_priority_score", "theme_similarity"],
                ascending=[True, False, False],
            )
            .reset_index(drop=True)
        )

        out = self.output_dir / "final_candidate_pool.csv"
        combined.to_csv(out, index=False, encoding="utf-8-sig")

        return combined
