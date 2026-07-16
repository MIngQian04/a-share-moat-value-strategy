from __future__ import annotations

from pathlib import Path

import pandas as pd


class ThemeCandidateDiscovery:
    """
    Discover stocks whose return behavior is similar
    to a theme seed basket.

    This module only discovers candidate stocks.
    It does not estimate true business exposure.

    Ranking metric:
        correlation only
    """

    def __init__(
        self,
        returns: pd.DataFrame,
        seed_path: str | Path = "config/cycle_theme_seed.csv",
        output_dir: str | Path = "data/processed/research",
    ):
        self.returns = returns.sort_index()
        self.seed = pd.read_csv(seed_path)

        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def build_theme_returns(self) -> pd.DataFrame:
        theme_returns = {}

        for theme, group in self.seed.groupby("theme"):
            codes = [
                code
                for code in group["ts_code"].astype(str)
                if code in self.returns.columns
            ]

            if not codes:
                continue

            weights = (
                group.set_index("ts_code")
                .loc[codes, "weight"]
                .astype(float)
            )

            weights = weights / weights.sum()

            theme_returns[theme] = (
                self.returns[codes]
                .mul(weights, axis=1)
                .sum(axis=1)
            )

        theme_returns = pd.DataFrame(
            theme_returns
        ).sort_index()

        theme_returns.to_parquet(
            self.output_dir / "theme_returns.parquet"
        )

        return theme_returns

    def discover(
        self,
        min_obs: int = 120,
        min_corr: float = 0.55,
        top_n: int = 50,
    ) -> pd.DataFrame:
        theme_returns = self.build_theme_returns()

        rows = []

        for theme in theme_returns.columns:
            theme_return = theme_returns[theme]

            for code in self.returns.columns:
                pair = pd.concat(
                    [
                        self.returns[code],
                        theme_return,
                    ],
                    axis=1,
                ).dropna()

                if len(pair) < min_obs:
                    continue

                corr = pair.iloc[:, 0].corr(
                    pair.iloc[:, 1]
                )

                if pd.isna(corr):
                    continue

                if corr < min_corr:
                    continue

                rows.append(
                    {
                        "ts_code": code,
                        "theme": theme,
                        "theme_similarity": corr,
                        "n_obs": len(pair),
                    }
                )

        candidates = pd.DataFrame(rows)

        if candidates.empty:
            return candidates

        candidates = (
            candidates
            .sort_values(
                ["theme", "theme_similarity"],
                ascending=[True, False],
            )
            .groupby("theme")
            .head(top_n)
            .reset_index(drop=True)
        )

        candidates.to_csv(
            self.output_dir / "theme_candidates.csv",
            index=False,
            encoding="utf-8-sig",
        )

        return candidates
