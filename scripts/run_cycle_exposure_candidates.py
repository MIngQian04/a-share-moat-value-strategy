# Allow running this file directly from the project root, e.g.
# python scripts/run_xxx.py
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from research.cycle_exposure import ThemeCandidateDiscovery


if __name__ == "__main__":
    returns = pd.read_parquet(
        "data/processed/research/returns.parquet"
    )

    discovery = ThemeCandidateDiscovery(returns)

    candidates = discovery.discover(
        min_obs=120,
        min_corr=0.55,
        top_n=50,
    )

    if candidates.empty:
        print("No candidates found.")
    else:
        for theme in candidates["theme"].unique():
            print(f"\n===== {theme.upper()} =====")

            result = candidates[candidates["theme"] == theme]

            print(
                result[
                    [
                        "ts_code",
                        "theme_similarity",
                        "n_obs",
                    ]
                ]
                .head(20)
                .to_string(index=False)
            )

    print("\nsaved: data/processed/research/theme_candidates.csv")
