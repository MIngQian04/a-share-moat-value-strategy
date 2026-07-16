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
from fundamental.fundamental_direction import FundamentalDirectionEngine


OPPORTUNITY_PATH = "data/processed/research/cycle_opportunity_rank.csv"
SURVIVAL_PATH = "data/processed/selection/survival_asset_capacity.csv"

OUTPUT_PATH = "data/processed/selection/fundamental_direction.csv"
AUDIT_PATH = "data/processed/selection/fundamental_direction_dropped_by_survival.csv"


DROP_SURVIVAL_STATUS = {
    "CAPACITY_EROSION",
    "DISTRESS",
}

DROP_CYCLE_PARTICIPATION = {
    "IMPAIRED",
}


def load_survival_filtered_candidates(
    opportunity_path: str = OPPORTUNITY_PATH,
    survival_path: str = SURVIVAL_PATH,
    top_n_per_theme: int = 20,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    opportunity = pd.read_csv(opportunity_path)
    survival = pd.read_csv(survival_path)

    if "theme_rank" in opportunity.columns:
        opportunity = (
            opportunity
            .sort_values(["theme", "theme_rank"])
            .groupby("theme")
            .head(top_n_per_theme)
            .reset_index(drop=True)
        )

    survival_cols = [
        "theme",
        "ts_code",
        "capacity_status",
        "survival_status",
        "distress_type",
        "cycle_participation",
        "financial_stress_flags",
        "capacity_flags",
        "asset_erosion_flags",
        "financial_stress_count",
        "asset_erosion_count",
    ]
    survival_cols = [c for c in survival_cols if c in survival.columns]

    merged = opportunity.merge(
        survival[survival_cols],
        on=["theme", "ts_code"],
        how="left",
        validate="many_to_one",
    )

    merged["survival_missing"] = merged["survival_status"].isna()

    drop_mask = (
        merged["survival_missing"]
        | merged["survival_status"].isin(DROP_SURVIVAL_STATUS)
        | merged["cycle_participation"].isin(DROP_CYCLE_PARTICIPATION)
    )

    dropped = merged[drop_mask].copy()
    passed = merged[~drop_mask].copy()

    return passed, dropped


if __name__ == "__main__":
    load_dotenv()
    decision_date = os.getenv("DECISION_DATE", "20260630")

    Path("data/processed/selection").mkdir(parents=True, exist_ok=True)

    candidates, dropped = load_survival_filtered_candidates(top_n_per_theme=20)

    dropped.to_csv(AUDIT_PATH, index=False, encoding="utf-8-sig")

    print(f"decision_date={decision_date}")
    print(f"survival passed candidates={len(candidates)}")
    print(f"dropped by survival={len(dropped)}")
    print(f"drop audit saved: {AUDIT_PATH}")

    if len(candidates) == 0:
        raise RuntimeError(
            "No candidates passed survival filter. Check survival_asset_capacity.csv."
        )

    store = FinancialPointInTimeStore(raw_dir="data/raw/fundamental")

    engine = FundamentalDirectionEngine(
        store=store,
        min_periods=6,
        recent_window=6,
        harvest_window=4,
    )

    result = engine.analyze_candidates(
        candidates=candidates,
        decision_date=decision_date,
    )

    survival_context_cols = [
        "theme",
        "ts_code",
        "capacity_status",
        "survival_status",
        "distress_type",
        "cycle_participation",
        "financial_stress_flags",
        "capacity_flags",
        "asset_erosion_flags",
    ]
    survival_context_cols = [c for c in survival_context_cols if c in candidates.columns]

    result = result.merge(
        candidates[survival_context_cols],
        on=["theme", "ts_code"],
        how="left",
    )

    result.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")

    priority = {
        "RECOVERING": 0,
        "BOTTOMING": 1,
        "DETERIORATING": 2,
        "HARVESTING": 3,
        "INSUFFICIENT_DATA": 4,
    }

    for theme in result["theme"].dropna().unique():
        print(f"\n===== {theme.upper()} FUNDAMENTAL DIRECTION AFTER SURVIVAL FILTER =====")

        theme_df = result[result["theme"] == theme].copy()
        theme_df["_priority"] = theme_df["fundamental_direction"].map(priority).fillna(9)

        display_cols = [
            "ts_code",
            "capacity_status",
            "survival_status",
            "cycle_participation",
            "fundamental_direction",
            "direction_score",
            "revenue_yoy",
            "ebit_margin",
            "ocf_margin",
            "revenue_yoy_slope",
            "ebit_margin_slope",
            "ocf_margin_slope",
            "strong_margin_periods",
            "direction_flags",
        ]
        display_cols = [c for c in display_cols if c in theme_df.columns]

        print(
            theme_df.sort_values(
                ["_priority", "direction_score"],
                ascending=[True, False],
            )[display_cols].to_string(index=False)
        )

    print(f"\nsaved: {OUTPUT_PATH}")
