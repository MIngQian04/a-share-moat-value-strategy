# Allow running this file directly from the project root, e.g.
# python scripts/run_xxx.py
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pathlib import Path
import os
import time

import pandas as pd
import tushare as ts
from dotenv import load_dotenv


START_DATE = "20190101"
END_DATE = "20260703"

TARGETS = {
    "coal": "601001.SH",
    "copper": "600301.SH",
    "fertilizer": "600141.SH",
    "lithium": "300390.SZ",
    "oil": "603619.SH",
    "solar": "688390.SH",
    "steel": "000959.SZ",
}

OUT_DIR = Path("data/processed/research")

CLOSE_PATH = OUT_DIR / "rank1_close.parquet"
OPEN_PATH = OUT_DIR / "rank1_open.parquet"
HIGH_PATH = OUT_DIR / "rank1_high.parquet"
LOW_PATH = OUT_DIR / "rank1_low.parquet"
VOLUME_PATH = OUT_DIR / "rank1_volume.parquet"
AMOUNT_PATH = OUT_DIR / "rank1_amount.parquet"

RAW_DIR = Path("data/raw/rank1_market_daily")


def get_pro():
    load_dotenv()

    token = os.getenv("TUSHARE_TOKEN")

    if not token:
        raise RuntimeError(
            "TUSHARE_TOKEN not found in .env"
        )

    ts.set_token(token)

    return ts.pro_api()


def download_daily(pro, theme, code):
    print(
        f"\n===== DOWNLOAD {theme.upper()} {code} ====="
    )

    df = pro.daily(
        ts_code=code,
        start_date=START_DATE,
        end_date=END_DATE,
    )

    if df is None or df.empty:
        print("NO DATA:", code)
        return None

    df["trade_date"] = pd.to_datetime(
        df["trade_date"],
        format="%Y%m%d",
    )

    df = (
        df
        .sort_values("trade_date")
        .drop_duplicates(
            ["ts_code", "trade_date"]
        )
        .reset_index(drop=True)
    )

    print(
        "rows:",
        len(df),
    )

    print(
        "date range:",
        df["trade_date"].min(),
        "→",
        df["trade_date"].max(),
    )

    print(
        "columns:",
        list(df.columns),
    )

    RAW_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    raw_path = (
        RAW_DIR
        / f"{theme}_{code.replace('.', '_')}.csv"
    )

    df.to_csv(
        raw_path,
        index=False,
        encoding="utf-8-sig",
    )

    print(
        "saved raw:",
        raw_path,
    )

    return df


def build_matrix(data, field):
    series = {}

    for theme, df in data.items():
        if field not in df.columns:
            print(
                "missing field:",
                theme,
                field,
            )
            continue

        s = (
            df
            .set_index("trade_date")[field]
        )

        s = pd.to_numeric(
            s,
            errors="coerce",
        )

        series[theme] = s

    matrix = (
        pd.DataFrame(series)
        .sort_index()
    )

    return matrix


def main():
    pro = get_pro()

    data = {}

    for theme, code in TARGETS.items():
        df = download_daily(
            pro,
            theme,
            code,
        )

        if df is not None:
            data[theme] = df

        time.sleep(0.35)

    if not data:
        raise RuntimeError(
            "No market data downloaded"
        )

    OUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    matrices = {
        "close": (
            build_matrix(data, "close"),
            CLOSE_PATH,
        ),
        "open": (
            build_matrix(data, "open"),
            OPEN_PATH,
        ),
        "high": (
            build_matrix(data, "high"),
            HIGH_PATH,
        ),
        "low": (
            build_matrix(data, "low"),
            LOW_PATH,
        ),
        "volume": (
            build_matrix(data, "vol"),
            VOLUME_PATH,
        ),
        "amount": (
            build_matrix(data, "amount"),
            AMOUNT_PATH,
        ),
    }

    print(
        "\n===== MATRIX COVERAGE ====="
    )

    for name, (
        matrix,
        path,
    ) in matrices.items():

        matrix.to_parquet(path)

        print(
            f"\n{name.upper()}"
        )

        print(
            "shape:",
            matrix.shape,
        )

        print(
            "date:",
            matrix.index.min(),
            "→",
            matrix.index.max(),
        )

        for theme in matrix.columns:
            valid = (
                matrix[theme]
                .dropna()
            )

            print(
                theme,
                "n=",
                len(valid),
                "start=",
                valid.index.min()
                if not valid.empty
                else None,
                "end=",
                valid.index.max()
                if not valid.empty
                else None,
            )

        print(
            "saved:",
            path,
        )


if __name__ == "__main__":
    main()
