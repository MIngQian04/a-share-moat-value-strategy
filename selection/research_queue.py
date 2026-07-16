from __future__ import annotations

from pathlib import Path
import pandas as pd

from selection.quant_screening import QuantStockScreener


class ResearchQueueBuilder:
    """
    Build a research queue from:
    - theme candidates from corr retrieval
    - manual candidates
    - quant screening metrics
    - optional moat review template

    Output is not final portfolio selection.
    Output is: which companies should be researched first.
    """

    def __init__(
        self,
        theme_candidates_path: str | Path = "data/processed/research/theme_candidates.csv",
        manual_candidates_path: str | Path = "config/manual_candidates.csv",
        security_master_path: str | Path = "data/processed/metadata/security_master.csv",
        moat_review_path: str | Path = "config/moat_review_template.csv",
        output_dir: str | Path = "data/processed/selection",
    ):
        self.theme_candidates_path = Path(theme_candidates_path)
        self.manual_candidates_path = Path(manual_candidates_path)
        self.security_master_path = Path(security_master_path)
        self.moat_review_path = Path(moat_review_path)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def load_theme_candidates(self) -> pd.DataFrame:
        if not self.theme_candidates_path.exists():
            return pd.DataFrame(columns=["ts_code", "theme", "theme_similarity", "n_obs"])

        df = pd.read_csv(self.theme_candidates_path)
        df["source_quant_retrieval"] = True
        return df

    def load_manual_candidates(self) -> pd.DataFrame:
        if not self.manual_candidates_path.exists():
            return pd.DataFrame(columns=["ts_code", "name", "theme", "reason"])

        df = pd.read_csv(self.manual_candidates_path)
        df["source_manual"] = True
        return df

    def load_security_master(self) -> pd.DataFrame:
        if not self.security_master_path.exists():
            return pd.DataFrame(columns=["ts_code", "name", "industry", "market"])

        sm = pd.read_csv(self.security_master_path)
        keep = [c for c in ["ts_code", "name", "industry", "market", "list_date", "list_status"] if c in sm.columns]
        return sm[keep].drop_duplicates("ts_code")

    def load_moat_review(self) -> pd.DataFrame:
        if not self.moat_review_path.exists():
            return pd.DataFrame(columns=["ts_code", "theme", "review_status", "moat_score"])

        df = pd.read_csv(self.moat_review_path)
        return df

    def build_candidate_pool(self) -> pd.DataFrame:
        quant = self.load_theme_candidates()
        manual = self.load_manual_candidates()
        security = self.load_security_master()

        if "source_manual" not in quant.columns:
            quant["source_manual"] = False
        if "source_quant_retrieval" not in manual.columns:
            manual["source_quant_retrieval"] = False

        if "theme_similarity" not in manual.columns:
            manual["theme_similarity"] = pd.NA
        if "n_obs" not in manual.columns:
            manual["n_obs"] = pd.NA
        if "reason" not in quant.columns:
            quant["reason"] = pd.NA

        combined = pd.concat([quant, manual], ignore_index=True, sort=False)

        if combined.empty:
            return combined

        combined["source_quant_retrieval"] = combined["source_quant_retrieval"].fillna(False).astype(bool)
        combined["source_manual"] = combined["source_manual"].fillna(False).astype(bool)

        combined = (
            combined.groupby(["ts_code", "theme"], as_index=False)
            .agg(
                {
                    "theme_similarity": "max",
                    "n_obs": "max",
                    "source_quant_retrieval": "max",
                    "source_manual": "max",
                    "reason": lambda x: "; ".join([str(v) for v in x.dropna().unique()]),
                }
            )
        )

        combined = combined.merge(security, on="ts_code", how="left")

        return combined

    def build(
        self,
        returns: pd.DataFrame,
        close: pd.DataFrame | None = None,
        pb_matrix: pd.DataFrame | None = None,
        top_n_per_theme: int = 10,
    ) -> pd.DataFrame:
        candidates = self.build_candidate_pool()

        if candidates.empty:
            return candidates

        screened = QuantStockScreener(
            returns=returns,
            close=close,
            pb_matrix=pb_matrix,
        ).screen(candidates)

        moat = self.load_moat_review()
        if not moat.empty:
            keep = [
                c for c in [
                    "ts_code",
                    "theme",
                    "review_status",
                    "moat_score",
                    "technology_moat",
                    "market_share_outlook",
                    "cost_advantage",
                    "substitution_risk",
                    "management_execution",
                    "bull_case",
                    "bear_case",
                    "sources",
                    "notes",
                ]
                if c in moat.columns
            ]
            screened = screened.merge(moat[keep], on=["ts_code", "theme"], how="left")

        screened["review_status"] = screened.get("review_status", pd.Series(index=screened.index, dtype="object")).fillna("NOT_REVIEWED")
        screened["moat_score"] = pd.to_numeric(screened.get("moat_score", pd.Series(index=screened.index)), errors="coerce")

        # Manual candidates are always kept in the queue, even if theme similarity is low or missing.
        screened["research_queue_flag"] = (
            screened["source_manual"].fillna(False)
            | screened["market_quality_pass"].fillna(False)
            | screened["theme_similarity"].ge(0.70).fillna(False)
        )

        queue = screened[screened["research_queue_flag"]].copy()

        queue = (
            queue.sort_values(
                ["theme", "source_manual", "research_priority_score", "theme_similarity"],
                ascending=[True, False, False, False],
            )
            .groupby("theme")
            .head(top_n_per_theme)
            .reset_index(drop=True)
        )

        out = self.output_dir / "research_queue.csv"
        queue.to_csv(out, index=False, encoding="utf-8-sig")

        full_out = self.output_dir / "screened_candidates_full.csv"
        screened.to_csv(full_out, index=False, encoding="utf-8-sig")

        return queue
