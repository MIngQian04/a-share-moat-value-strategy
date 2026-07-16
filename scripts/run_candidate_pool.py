# Allow running this file directly from the project root, e.g.
# python scripts/run_xxx.py
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from selection.candidate_pool import CandidatePoolBuilder

if __name__ == "__main__":
    pool = CandidatePoolBuilder().build()

    if pool.empty:
        print("Candidate pool is empty.")
    else:
        for theme in pool["theme"].dropna().unique():
            print(f"\n===== {theme.upper()} =====")
            cols = [
                "ts_code",
                "name",
                "industry",
                "theme_similarity",
                "survival_advantage_score",
                "candidate_priority_score",
                "source_quant",
                "source_manual",
            ]
            cols = [c for c in cols if c in pool.columns]
            print(pool[pool["theme"] == theme][cols].head(20).to_string(index=False))

    print("\nsaved: data/processed/selection/final_candidate_pool.csv")
