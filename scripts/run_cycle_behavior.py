# Allow running this file directly from the project root, e.g.
# python scripts/run_xxx.py
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from cycle_behavior.behavior_analyzer import CycleBehaviorAnalyzer


if __name__ == "__main__":
    candidates = pd.read_csv("data/processed/research/theme_candidates.csv")
    returns = pd.read_parquet("data/processed/research/returns.parquet")
    theme_returns = pd.read_parquet("data/processed/research/theme_returns.parquet")

    analyzer = CycleBehaviorAnalyzer(
        stock_returns=returns,
        theme_returns=theme_returns,
        min_obs=120,
        lead_lag_window=5,
    )

    behavior = analyzer.analyze(candidates)

    out_path = "data/processed/research/cycle_behavior.csv"
    behavior.to_csv(out_path, index=False, encoding="utf-8-sig")

    for theme in behavior["theme"].dropna().unique():
        print(f"\n===== {theme.upper()} CYCLE BEHAVIOR V2 =====")
        cols = [
            "ts_code",
            "theme_similarity",
            "upside_elasticity",
            "downside_elasticity",
            "cycle_convexity",
            "lead_score",
            "lag_score",
            "lead_lag_window",
            "elasticity_class",
            "leadership_class",
            "cycle_behavior_profile",
        ]
        cols = [c for c in cols if c in behavior.columns]

        print(
            behavior[behavior["theme"] == theme][cols]
            .sort_values(
                ["leadership_class", "elasticity_class", "theme_similarity"],
                ascending=[True, True, False],
            )
            .head(25)
            .to_string(index=False)
        )

    print(f"\nsaved: {out_path}")
