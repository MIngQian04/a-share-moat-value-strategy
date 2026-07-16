# Allow running this file directly from the project root, e.g.
# python scripts/run_xxx.py
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from survival.survival_engine import SurvivalAssetCapacityEngine


INPUT_PATH = "data/processed/fundamental/survival_input.csv"
OUTPUT_PATH = "data/processed/selection/survival_asset_capacity.csv"


if __name__ == "__main__":
    financials = pd.read_csv(INPUT_PATH)

    engine = SurvivalAssetCapacityEngine()
    result = engine.analyze(financials)

    result.to_csv(
        OUTPUT_PATH,
        index=False,
        encoding="utf-8-sig",
    )

    display_cols = [
        "theme",
        "ts_code",
        "total_assets_yoy",
        "fixed_assets_yoy",
        "construction_in_progress_yoy",
        "capex_to_assets",
        "asset_disposal_to_assets",
        "asset_disposal_to_capex",
        "cash_to_short_debt",
        "interest_coverage",
        "ocf_to_debt",
        "financial_stress_count",
        "asset_erosion_count",
        "capacity_status",
        "survival_status",
        "distress_type",
        "cycle_participation",
    ]

    display_cols = [c for c in display_cols if c in result.columns]

    for theme in result["theme"].dropna().unique():
        print(f"\n===== {theme.upper()} SURVIVAL / CAPACITY V2 =====")
        theme_df = result[result["theme"] == theme].copy()

        priority = {
            "CAPACITY_EROSION": 0,
            "DISTRESS": 1,
            "WATCH": 2,
            "SAFE": 3,
        }
        theme_df["_priority"] = theme_df["survival_status"].map(priority).fillna(9)

        print(
            theme_df.sort_values(
                ["_priority", "asset_erosion_count", "financial_stress_count"],
                ascending=[True, False, False],
            )[display_cols]
            .to_string(index=False)
        )

    print(f"\nsaved: {OUTPUT_PATH}")
