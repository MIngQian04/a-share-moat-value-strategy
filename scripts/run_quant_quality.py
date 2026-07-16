# Allow running this file directly from the project root, e.g.
# python scripts/run_xxx.py
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from fundamental.point_in_time import FinancialPointInTimeStore
from quality.quant_quality import QuantQualityEngine


INPUT_PATH = "data/processed/selection/fundamental_direction.csv"
OUTPUT_PATH = "data/processed/selection/quant_quality_v3.csv"


if __name__ == "__main__":
    load_dotenv()
    decision_date = os.getenv("DECISION_DATE", "20260630")

    Path("data/processed/selection").mkdir(parents=True, exist_ok=True)

    candidates = pd.read_csv(INPUT_PATH)

    store = FinancialPointInTimeStore(raw_dir="data/raw/fundamental")

    engine = QuantQualityEngine(
        store=store,
        min_annual_periods=3,
        lookback_years=5,
    )

    quality = engine.analyze_candidates(
        candidates=candidates,
        decision_date=decision_date,
    )

    context_cols = [
        "theme",
        "ts_code",
        "capacity_status",
        "survival_status",
        "cycle_participation",
        "fundamental_direction",
        "direction_score",
    ]
    context_cols = [c for c in context_cols if c in candidates.columns]

    result = quality.merge(
        candidates[context_cols],
        on=["theme", "ts_code"],
        how="left",
        validate="one_to_one",
    )

    result.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")

    for theme in result["theme"].dropna().unique():
        print(f"\n===== {theme.upper()} QUANT QUALITY V3 =====")

        theme_df = result[result["theme"] == theme].copy()

        display_cols = [
            "quant_quality_rank",
            "ts_code",
            "fundamental_direction",
            "annual_periods",
            "median_roic_proxy",
            "median_cash_conversion",
            "median_fcf_realization",
            "roic_persistence_score",
            "cash_quality_score",
            "quant_quality_score",
            "quality_evidence",
        ]

        print(
            theme_df.sort_values(
                ["quant_quality_rank", "quant_quality_score"],
                ascending=[True, False],
            )[display_cols].to_string(index=False)
        )

    print(f"\nsaved: {OUTPUT_PATH}")
