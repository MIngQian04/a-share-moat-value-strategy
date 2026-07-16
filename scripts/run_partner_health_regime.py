# Allow running this file directly from the project root, e.g.
# python scripts/run_xxx.py
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pathlib import Path
import numpy as np
import pandas as pd

RETURNS_PATH = Path(
    "data/processed/selection/stock_return_matrix.csv"
)

QUALIFIED_PATH = Path(
    "data/processed/selection/qualified_complement_pairs.csv"
)

OUT_DAILY = Path(
    "data/processed/selection/partner_health_regime_daily.csv"
)

OUT_SUMMARY = Path(
    "data/processed/selection/partner_health_regime_summary.csv"
)

TRADING_DAYS = 252

LOOKBACK = 120
MIN_OBS = 60

# ------------------------------------------------------------
# Individual Partner Health Gates
# ------------------------------------------------------------

MIN_ROLLING_RETURN = -0.10
MAX_ROLLING_VOL = 0.35
MAX_ROLLING_DRAWDOWN = -0.30

# ------------------------------------------------------------
# Universe Regime Thresholds
# ------------------------------------------------------------

HEALTHY_RATIO = 0.60
WEAK_RATIO = 0.30


def rolling_max_drawdown(series):
    nav = (1.0 + series).cumprod()
    dd = nav / nav.cummax() - 1.0
    return float(dd.min())


def annualized_return(series):
    series = series.dropna()

    if len(series) < MIN_OBS:
        return np.nan

    nav = float((1.0 + series).prod())

    if nav <= 0:
        return np.nan

    years = len(series) / TRADING_DAYS

    return nav ** (1.0 / years) - 1.0


def annualized_vol(series):
    series = series.dropna()

    if len(series) < MIN_OBS:
        return np.nan

    return float(
        series.std() * np.sqrt(TRADING_DAYS)
    )


def load_partner_universe():
    df = pd.read_csv(QUALIFIED_PATH)

    codes = (
        df["candidate_ts_code"]
        .dropna()
        .astype(str)
        .unique()
        .tolist()
    )

    return sorted(codes)


def classify_stock_health(
    rolling_return,
    rolling_vol,
    rolling_drawdown,
):
    reasons = []

    if pd.isna(rolling_return):
        reasons.append("INSUFFICIENT_RETURN_HISTORY")
    elif rolling_return < MIN_ROLLING_RETURN:
        reasons.append("POOR_RETURN")

    if pd.isna(rolling_vol):
        reasons.append("INSUFFICIENT_VOL_HISTORY")
    elif rolling_vol > MAX_ROLLING_VOL:
        reasons.append("HIGH_VOL")

    if pd.isna(rolling_drawdown):
        reasons.append("INSUFFICIENT_DRAWDOWN_HISTORY")
    elif rolling_drawdown < MAX_ROLLING_DRAWDOWN:
        reasons.append("DEEP_DRAWDOWN")

    healthy = len(reasons) == 0

    return healthy, "|".join(reasons)


def classify_regime(healthy_ratio):
    if pd.isna(healthy_ratio):
        return "UNKNOWN"

    if healthy_ratio >= HEALTHY_RATIO:
        return "HEALTHY"

    if healthy_ratio >= WEAK_RATIO:
        return "WEAK"

    return "STRESSED"


def main():
    returns = pd.read_csv(RETURNS_PATH)

    returns["trade_date"] = pd.to_datetime(
        returns["trade_date"]
    )

    returns = (
        returns
        .set_index("trade_date")
        .sort_index()
    )

    partner_codes = load_partner_universe()

    partner_codes = [
        code
        for code in partner_codes
        if code in returns.columns
    ]

    print(
        "partner universe size:",
        len(partner_codes),
    )

    print(
        "partner universe:",
        partner_codes,
    )

    rows = []

    dates = returns.index

    for i, dt in enumerate(dates):
        if i + 1 < MIN_OBS:
            continue

        start = max(
            0,
            i - LOOKBACK + 1,
        )

        window = returns.iloc[
            start:i + 1
        ]

        stock_health = []

        for code in partner_codes:
            r = window[code].dropna()

            if len(r) < MIN_OBS:
                continue

            ann_ret = annualized_return(r)
            ann_vol = annualized_vol(r)
            max_dd = rolling_max_drawdown(r)

            healthy, reasons = classify_stock_health(
                ann_ret,
                ann_vol,
                max_dd,
            )

            stock_health.append(
                {
                    "code": code,
                    "healthy": healthy,
                    "ann_return": ann_ret,
                    "ann_vol": ann_vol,
                    "max_drawdown": max_dd,
                    "reasons": reasons,
                }
            )

        if not stock_health:
            continue

        health_df = pd.DataFrame(stock_health)

        healthy_count = int(
            health_df["healthy"].sum()
        )

        total_count = len(health_df)

        healthy_ratio = (
            healthy_count / total_count
        )

        regime = classify_regime(
            healthy_ratio
        )

        median_return = float(
            health_df["ann_return"].median()
        )

        median_vol = float(
            health_df["ann_vol"].median()
        )

        median_drawdown = float(
            health_df["max_drawdown"].median()
        )

        rows.append(
            {
                "trade_date": dt,
                "partner_count": total_count,
                "healthy_count": healthy_count,
                "healthy_ratio": healthy_ratio,
                "median_ann_return": median_return,
                "median_ann_vol": median_vol,
                "median_max_drawdown": median_drawdown,
                "partner_regime": regime,
            }
        )

    daily = pd.DataFrame(rows)

    daily.to_csv(
        OUT_DAILY,
        index=False,
        encoding="utf-8-sig",
    )

    regime_summary = (
        daily["partner_regime"]
        .value_counts()
        .rename_axis("partner_regime")
        .reset_index(name="days")
    )

    regime_summary["day_ratio"] = (
        regime_summary["days"]
        / regime_summary["days"].sum()
    )

    regime_summary.to_csv(
        OUT_SUMMARY,
        index=False,
        encoding="utf-8-sig",
    )

    print(
        "\n===== PARTNER HEALTH REGIME SUMMARY ====="
    )

    print(
        regime_summary
        .round(4)
        .to_string(index=False)
    )

    print(
        "\n===== LATEST PARTNER HEALTH ====="
    )

    print(
        daily.tail(20)
        .round(4)
        .to_string(index=False)
    )

    print(
        "\nsaved:",
        OUT_DAILY,
    )

    print(
        "saved:",
        OUT_SUMMARY,
    )


if __name__ == "__main__":
    main()
