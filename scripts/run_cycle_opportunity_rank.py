# Allow running this file directly from the project root, e.g.
# python scripts/run_xxx.py
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from ranking.cycle_opportunity_ranker import CycleOpportunityRanker


if __name__ == "__main__":
    behavior = pd.read_csv(
        "data/processed/research/cycle_behavior.csv"
    )

    ranker = CycleOpportunityRanker(
        min_theme_similarity=0.55,
        explosive_upside=1.20,
        strong_convexity=1.20,
        high_risk_downside=1.20,
    )

    ranked = ranker.rank(behavior)

    out_path = (
        "data/processed/research/"
        "cycle_opportunity_rank.csv"
    )

    ranked.to_csv(
        out_path,
        index=False,
        encoding="utf-8-sig",
    )

    display_cols = [
        "theme_rank",
        "ts_code",
        "theme_similarity",
        "upside_elasticity",
        "downside_elasticity",
        "cycle_convexity",
        "opportunity_class",
        "upside_rank_pct",
        "convexity_rank_pct",
    ]

    display_cols = [
        c for c in display_cols
        if c in ranked.columns
    ]

    for theme in ranked["theme"].dropna().unique():
        print(
            f"\n===== {theme.upper()} "
            "CYCLE OPPORTUNITY RANK ====="
        )

        theme_ranked = ranked[
            ranked["theme"] == theme
        ]

        print(
            theme_ranked[display_cols]
            .head(20)
            .to_string(index=False)
        )

    print(f"\nsaved: {out_path}")
