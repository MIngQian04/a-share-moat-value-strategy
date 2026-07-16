# Allow running this file directly from the project root, e.g.
# python scripts/run_xxx.py
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from selection.research_queue import ResearchQueueBuilder


if __name__ == "__main__":
    returns = pd.read_parquet("data/processed/research/returns.parquet")
    close = pd.read_parquet("data/processed/research/close.parquet")

    builder = ResearchQueueBuilder()
    queue = builder.build(
        returns=returns,
        close=close,
        pb_matrix=None,
        top_n_per_theme=10,
    )

    if queue.empty:
        print("Research queue is empty.")
    else:
        for theme in queue["theme"].dropna().unique():
            print(f"\n===== {theme.upper()} RESEARCH QUEUE =====")
            cols = [
                "ts_code",
                "name",
                "industry",
                "theme_similarity",
                "sharpe",
                "sortino",
                "max_drawdown",
                "market_quality_pass",
                "valuation_context",
                "review_status",
                "moat_score",
                "source_manual",
                "source_quant_retrieval",
            ]
            cols = [c for c in cols if c in queue.columns]
            print(queue[queue["theme"] == theme][cols].to_string(index=False))

    print("\nsaved: data/processed/selection/research_queue.csv")
    print("saved: data/processed/selection/screened_candidates_full.csv")
