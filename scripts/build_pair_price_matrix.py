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
from dotenv import load_dotenv
import tushare as ts

START_DATE = "20190101"
END_DATE = "20260704"

BASE = Path("data/processed")
SEL = BASE / "selection"
SEL.mkdir(parents=True, exist_ok=True)

FINAL_CANDIDATES = SEL / "final_candidates.csv"
OUT_CLOSE = SEL / "pair_close_matrix.csv"
OUT_RET = SEL / "stock_return_matrix.csv"

# 互补候选池：先用核心资产，后面再扩展
COMPLEMENT_CANDIDATES = [
    # 水电/公用事业
    "600900.SH",  # 长江电力
    "600886.SH",  # 国投电力
    "600027.SH",  # 华电国际
    "600011.SH",  # 华能国际

    # 白酒/消费
    "600519.SH",  # 贵州茅台
    "000858.SZ",  # 五粮液
    "000568.SZ",  # 泸州老窖

    # 银行
    "600036.SH",  # 招商银行
    "601398.SH",  # 工商银行
    "601288.SH",  # 农业银行
    "601939.SH",  # 建设银行
    "601166.SH",  # 兴业银行
    "600000.SH",  # 浦发银行

    # 券商
    "600030.SH",  # 中信证券
    "600837.SH",  # 海通证券
    "601688.SH",  # 华泰证券
    "601211.SH",  # 国泰君安

    # 运营商/高股息
    "600941.SH",  # 中国移动
    "601728.SH",  # 中国电信
    "600050.SH",  # 中国联通
]


def get_token():
    load_dotenv()
    token = os.getenv("TUSHARE_TOKEN") or os.getenv("TS_TOKEN") or os.getenv("TUSHARE_API_TOKEN")
    if not token:
        raise RuntimeError("没有找到 Tushare token。请确认 .env 里有 TUSHARE_TOKEN=你的token")
    return token


def get_rank1_codes():
    fc = pd.read_csv(FINAL_CANDIDATES)
    rank_col = "assembly_rank" if "assembly_rank" in fc.columns else "theme_rank"
    rank1 = fc[fc[rank_col] == 1]["ts_code"].dropna().astype(str).tolist()
    return rank1


def fetch_close(pro, ts_code):
    print(f"fetching {ts_code} ...")
    df = pro.daily(ts_code=ts_code, start_date=START_DATE, end_date=END_DATE)
    if df is None or df.empty:
        print(f"  empty: {ts_code}")
        return None
    df = df[["trade_date", "close"]].copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df = df.sort_values("trade_date")
    df = df.drop_duplicates("trade_date")
    df = df.set_index("trade_date")
    df = df.rename(columns={"close": ts_code})
    return df


def main():
    token = get_token()
    ts.set_token(token)
    pro = ts.pro_api(token)

    rank1_codes = get_rank1_codes()
    codes = sorted(set(rank1_codes + COMPLEMENT_CANDIDATES))

    print("rank1 codes:", rank1_codes)
    print("total codes to fetch:", len(codes))

    frames = []
    for code in codes:
        try:
            df = fetch_close(pro, code)
            if df is not None:
                frames.append(df)
        except Exception as e:
            print(f"  failed {code}: {e}")

    if not frames:
        raise RuntimeError("没有拉到任何价格数据")

    close = pd.concat(frames, axis=1).sort_index()
    ret = close.pct_change()

    close_out = close.reset_index().rename(columns={"trade_date": "trade_date"})
    ret_out = ret.reset_index().rename(columns={"trade_date": "trade_date"})

    close_out.to_csv(OUT_CLOSE, index=False)
    ret_out.to_csv(OUT_RET, index=False)

    print("\nsaved:", OUT_CLOSE, close_out.shape)
    print("saved:", OUT_RET, ret_out.shape)
    print("rank1 coverage:", sorted(set(rank1_codes) & set(ret.columns)))
    print("missing rank1:", [c for c in rank1_codes if c not in ret.columns])


if __name__ == "__main__":
    main()
