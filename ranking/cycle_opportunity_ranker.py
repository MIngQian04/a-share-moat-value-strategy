from __future__ import annotations

import numpy as np
import pandas as pd


class CycleOpportunityRanker:
    """
    Rank stocks AFTER theme-correlation retrieval and cycle-behavior analysis.

    Logic:
        1. Corr is a gate, not a weighted score.
        2. Upside elasticity is the primary ranking variable.
        3. Convexity is a secondary ranking variable.
        4. Downside elasticity is retained as risk context.
        5. Lead/Lag is observational only and does not affect rank.
    """

    def __init__(
        self,
        min_theme_similarity: float = 0.55,
        explosive_upside: float = 1.20,
        strong_convexity: float = 1.20,
        high_risk_downside: float = 1.20,
    ):
        self.min_theme_similarity = min_theme_similarity
        self.explosive_upside = explosive_upside
        self.strong_convexity = strong_convexity
        self.high_risk_downside = high_risk_downside

    def classify_opportunity(self, row: pd.Series) -> str:
        up = row["upside_elasticity"]
        down = row["downside_elasticity"]
        convexity = row["cycle_convexity"]

        if pd.isna(up) or pd.isna(down) or pd.isna(convexity):
            return "UNKNOWN"

        if up >= self.explosive_upside and convexity >= self.strong_convexity:
            return "ASYMMETRIC_WINNER"

        if up >= self.explosive_upside and down >= self.high_risk_downside:
            return "HIGH_RISK_BETA"

        if up >= self.explosive_upside:
            return "CYCLICAL_EXPLOSIVE"

        if up >= 1.0:
            return "PURE_BETA"

        return "LOW_ELASTICITY"

    @staticmethod
    def _percentile_rank(series: pd.Series) -> pd.Series:
        return series.rank(method="average", pct=True)

    def rank_theme(self, theme_df: pd.DataFrame) -> pd.DataFrame:
        df = theme_df.copy()

        # Corr is a hard retrieval gate.
        df = df[df["theme_similarity"] >= self.min_theme_similarity].copy()

        df["opportunity_class"] = df.apply(
            self.classify_opportunity,
            axis=1,
        )

        # Rank components are kept separate for interpretability.
        df["upside_rank_pct"] = self._percentile_rank(
            df["upside_elasticity"]
        )

        df["convexity_rank_pct"] = self._percentile_rank(
            df["cycle_convexity"]
        )

        # Lexicographic ranking:
        # primary = upside elasticity
        # secondary = convexity
        # tertiary = theme similarity
        df = df.sort_values(
            [
                "upside_elasticity",
                "cycle_convexity",
                "theme_similarity",
            ],
            ascending=[False, False, False],
            na_position="last",
        ).reset_index(drop=True)

        df["theme_rank"] = np.arange(1, len(df) + 1)

        return df

    def rank(self, behavior: pd.DataFrame) -> pd.DataFrame:
        required = {
            "ts_code",
            "theme",
            "theme_similarity",
            "upside_elasticity",
            "downside_elasticity",
            "cycle_convexity",
        }

        missing = required - set(behavior.columns)
        if missing:
            raise ValueError(
                f"cycle_behavior.csv missing columns: {sorted(missing)}"
            )

        ranked = []

        for theme, theme_df in behavior.groupby("theme", sort=True):
            ranked.append(self.rank_theme(theme_df))

        if not ranked:
            return pd.DataFrame()

        return pd.concat(ranked, ignore_index=True)
