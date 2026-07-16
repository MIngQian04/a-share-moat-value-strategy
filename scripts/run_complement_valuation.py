# Allow running this file directly from the project root, e.g.
# python scripts/run_xxx.py
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pathlib import Path
import os
import sys
import time
import pandas as pd
from dotenv import load_dotenv
import tushare as ts

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from selection.complement_valuation import ComplementValuationConfig, ComplementValuationEngine

FINAL = Path("data/processed/selection/final_candidates.csv")
RETURNS = Path("data/processed/selection/stock_return_matrix.csv")
SECURITY_MASTER = Path("data/processed/metadata/security_master.csv")
OUT_RAW = Path("data/processed/selection/complement_daily_basic.csv")
OUT_VAL = Path("data/processed/selection/complement_valuation.csv")

START_DATE = "20190101"
END_DATE = "20260704"


def get_token() -> str:
    load_dotenv()
    token = os.getenv("TUSHARE_TOKEN") or os.getenv("TS_TOKEN") or os.getenv("TUSHARE_API_TOKEN")
    if not token:
        raise RuntimeError("没有找到 Tushare token。请确认当前项目 .env 中存在 TUSHARE_TOKEN/TS_TOKEN/TUSHARE_API_TOKEN")
    return token


def main() -> None:
    fc = pd.read_csv(FINAL)
    ret = pd.read_csv(RETURNS)
    sm = pd.read_csv(SECURITY_MASTER)

    cycle_codes = set(
        fc.loc[pd.to_numeric(fc["assembly_rank"], errors="coerce").eq(1), "ts_code"]
        .dropna().astype(str)
    )
    candidate_codes = [c for c in ret.columns if c != "trade_date" and c not in cycle_codes]

    token = get_token()
    ts.set_token(token)
    pro = ts.pro_api(token)

    frames = []
    for code in candidate_codes:
        print(f"fetching valuation history {code} ...")
        try:
            df = pro.daily_basic(
                ts_code=code,
                start_date=START_DATE,
                end_date=END_DATE,
                fields="ts_code,trade_date,pe_ttm,pb,dv_ttm",
            )
            if df is not None and not df.empty:
                frames.append(df)
            time.sleep(0.12)
        except Exception as exc:
            print(f"  failed {code}: {exc}")

    if not frames:
        raise RuntimeError("没有拉到 daily_basic 数据")

    raw = pd.concat(frames, ignore_index=True)
    OUT_RAW.parent.mkdir(parents=True, exist_ok=True)
    raw.to_csv(OUT_RAW, index=False, encoding="utf-8-sig")

    engine = ComplementValuationEngine(ComplementValuationConfig(min_obs=120))
    result = engine.build(raw, sm)
    result.to_csv(OUT_VAL, index=False, encoding="utf-8-sig")

    print(f"\nsaved: {OUT_RAW} {raw.shape}")
    print(f"saved: {OUT_VAL} {result.shape}")
    print("\n===== COMPLEMENT VALUATION =====")
    cols = ["ts_code", "name", "industry", "valuation_model", "valuation_score",
            "pe_percentile", "pb_percentile", "dividend_yield_percentile",
            "valuation_status", "valuation_components"]
    print(result[cols].to_string(index=False))


if __name__ == "__main__":
    main()
