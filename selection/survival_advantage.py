from __future__ import annotations

from pathlib import Path
import pandas as pd


SURVIVAL_COLUMNS = [
    "technology_leadership",
    "market_share_trend",
    "cost_curve_position",
    "rd_persistence",
    "balance_sheet_buffer",
    "capacity_survival",
    "management_quality",
]


DEFAULT_WEIGHTS = {
    "technology_leadership": 0.25,
    "market_share_trend": 0.18,
    "cost_curve_position": 0.18,
    "rd_persistence": 0.14,
    "balance_sheet_buffer": 0.10,
    "capacity_survival": 0.10,
    "management_quality": 0.05,
}


class SurvivalAdvantageScorer:
    """
    Buffett-side review layer for cyclical stocks.

    This module answers:
        Which companies can survive the downcycle and become stronger?

    Inputs are human-reviewable scores in [0, 1].
    """

    def __init__(
        self,
        review_path: str | Path = "config/survival_advantage_template.csv",
        weights: dict | None = None,
    ):
        self.review_path = Path(review_path)
        self.weights = weights or DEFAULT_WEIGHTS

    def load_review(self) -> pd.DataFrame:
        if not self.review_path.exists():
            return pd.DataFrame(
                columns=["ts_code", "name", "theme"] + SURVIVAL_COLUMNS + ["notes"]
            )

        df = pd.read_csv(self.review_path)

        for col in SURVIVAL_COLUMNS:
            if col not in df.columns:
                df[col] = 0.0
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0).clip(0, 1)

        return df

    def score(self) -> pd.DataFrame:
        df = self.load_review()

        if df.empty:
            df["survival_advantage_score"] = []
            return df

        score = pd.Series(0.0, index=df.index)

        for col, weight in self.weights.items():
            score += df[col] * weight

        df["survival_advantage_score"] = score.clip(0, 1)

        return (
            df.sort_values(["theme", "survival_advantage_score"], ascending=[True, False])
            .reset_index(drop=True)
        )
