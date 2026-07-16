# Allow running this file directly from the project root, e.g.
# python scripts/run_xxx.py
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from exposure.exposure_classifier import CycleExposureClassifier


if __name__ == "__main__":
    path = "data/processed/selection/screened_candidates_full.csv"

    candidates = pd.read_csv(path)

    classifier = CycleExposureClassifier()
    classified = classifier.classify(candidates)

    out_path = "data/processed/selection/classified_candidates.csv"
    classified.to_csv(out_path, index=False, encoding="utf-8-sig")

    for theme in classified["theme"].dropna().unique():
        print(f"\n===== {theme.upper()} EXPOSURE TYPES =====")
        cols = [
            "ts_code",
            "name",
            "industry",
            "theme_similarity",
            "exposure_type",
            "exposure_confidence",
            "exposure_source",
            "exposure_reason",
        ]
        cols = [c for c in cols if c in classified.columns]
        print(classified[classified["theme"] == theme][cols].head(30).to_string(index=False))

    print(f"\nsaved: {out_path}")
