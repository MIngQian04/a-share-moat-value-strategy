# Allow running this file directly from the project root, e.g.
# python scripts/run_xxx.py
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pathlib import Path
import os
import pandas as pd
import tushare as ts
from dotenv import load_dotenv

from fundamental.tushare_financial_loader import TushareFinancialLoader
from fundamental.point_in_time import FinancialPointInTimeStore
from fundamental.survival_input_builder import SurvivalInputBuilder


def load_candidates(
    path: str = "data/processed/research/cycle_opportunity_rank.csv",
    top_n_per_theme: int = 20,
) -> pd.DataFrame:
    candidates = pd.read_csv(path)

    if "theme_rank" in candidates.columns:
        candidates = (
            candidates
            .sort_values(["theme", "theme_rank"])
            .groupby("theme")
            .head(top_n_per_theme)
            .reset_index(drop=True)
        )

    return candidates


if __name__ == "__main__":
    load_dotenv()

    token = os.getenv("TUSHARE_TOKEN")
    if not token:
        raise RuntimeError(
            "TUSHARE_TOKEN not found. Please set it in .env"
        )

    ts.set_token(token)
    pro = ts.pro_api()

    decision_date = os.getenv("DECISION_DATE", "20260630")

    candidates = load_candidates(
        top_n_per_theme=20,
    )

    codes = sorted(candidates["ts_code"].astype(str).unique())

    print(f"decision_date={decision_date}")
    print(f"candidate codes={len(codes)}")

    loader = TushareFinancialLoader(
        pro=pro,
        raw_dir="data/raw/fundamental",
        sleep_seconds=0.25,
    )

    loader.download_for_codes(
        codes=codes,
        start_date="20180101",
        end_date=decision_date,
        force=False,
    )

    store = FinancialPointInTimeStore(
        raw_dir="data/raw/fundamental",
    )

    builder = SurvivalInputBuilder(store)

    survival_input = builder.build_for_candidates(
        candidates=candidates,
        decision_date=decision_date,
    )

    print("survival_input:", survival_input.shape)
    print(
        survival_input[
            [
                "theme",
                "ts_code",
                "financial_end_date",
                "financial_ann_date",
                "cash",
                "short_debt",
                "total_assets",
                "fixed_assets",
                "revenue",
                "operating_cash_flow",
            ]
        ]
        .head(20)
        .to_string(index=False)
    )

    print(
        "\nsaved: "
        "data/processed/fundamental/survival_input.csv"
    )
