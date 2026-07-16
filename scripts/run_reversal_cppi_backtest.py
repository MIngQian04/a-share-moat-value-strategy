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

CLOSE_PATH = Path("data/processed/selection/pair_close_matrix.csv")
RETURNS_PATH = Path("data/processed/selection/stock_return_matrix.csv")
PAIRS_PATH = Path("data/processed/selection/complement_pairs.csv")

OUT_SUMMARY = Path("data/processed/selection/reversal_cppi_summary.csv")
OUT_NAV = Path("data/processed/selection/reversal_cppi_nav.csv")

TRADING_DAYS = 252

LOW_POSITION_THRESHOLD = 0.30
THREE_DAY_RETURN_THRESHOLD = 0.05

MAX_DRAWDOWN_LIMIT = 0.20
CPPI_MULTIPLIER = 3.0
MAX_CYCLE_WEIGHT = 0.80


def max_drawdown(ret):
    nav = (1 + ret).cumprod()
    return float((nav / nav.cummax() - 1).min())


def annual_return(ret):
    ret = ret.dropna()
    nav = float((1 + ret).prod())
    years = len(ret) / TRADING_DAYS
    return nav ** (1 / years) - 1 if years > 0 and nav > 0 else np.nan


def annual_vol(ret):
    return float(ret.dropna().std() * np.sqrt(TRADING_DAYS))


def sharpe(ret):
    ret = ret.dropna()
    sd = ret.std()
    return float(ret.mean() / sd * np.sqrt(TRADING_DAYS)) if sd and not np.isnan(sd) else np.nan


def sortino(ret):
    ret = ret.dropna()
    downside = ret[ret < 0]
    sd = downside.std()
    return float(ret.mean() / sd * np.sqrt(TRADING_DAYS)) if sd and not np.isnan(sd) else np.nan


def calmar(ret):
    dd = abs(max_drawdown(ret))
    return float(annual_return(ret) / dd) if dd else np.nan


def metrics(ret):
    ret = ret.dropna()
    return {
        "n_obs": len(ret),
        "annual_return": annual_return(ret),
        "annual_vol": annual_vol(ret),
        "sharpe": sharpe(ret),
        "sortino": sortino(ret),
        "max_drawdown": max_drawdown(ret),
        "calmar": calmar(ret),
        "final_nav": float((1 + ret).prod()),
    }


def build_price_reversal_signal(close_series):
    df = pd.DataFrame({"close": close_series}).dropna()
    df["low_252"] = df["close"].rolling(252, min_periods=120).min()
    df["high_252"] = df["close"].rolling(252, min_periods=120).max()
    df["position_252"] = (df["close"] - df["low_252"]) / (df["high_252"] - df["low_252"])

    df["up_day"] = df["close"] > df["close"].shift(1)
    df["three_up"] = df["up_day"] & df["up_day"].shift(1) & df["up_day"].shift(2)
    df["three_day_return"] = df["close"] / df["close"].shift(3) - 1

    df["low_position_gate"] = df["position_252"].shift(3) <= LOW_POSITION_THRESHOLD
    df["reversal_signal"] = (
        df["low_position_gate"]
        & df["three_up"]
        & (df["three_day_return"] >= THREE_DAY_RETURN_THRESHOLD)
    )

    return df


def run_reversal_gated_cppi(cycle_ret, partner_ret, close_series):
    signal = build_price_reversal_signal(close_series)

    common = cycle_ret.dropna().index.intersection(partner_ret.dropna().index).intersection(signal.index)
    cycle_ret = cycle_ret.loc[common]
    partner_ret = partner_ret.loc[common]
    signal = signal.loc[common]

    nav = 1.0
    peak = 1.0
    cppi_active = False

    rows = []

    for dt in common:
        reversal = bool(signal.loc[dt, "reversal_signal"])

        if reversal:
            cppi_active = True

        peak = max(peak, nav)
        floor = peak * (1 - MAX_DRAWDOWN_LIMIT)
        cushion = max((nav - floor) / nav, 0.0)

        if cppi_active:
            cycle_w = min(MAX_CYCLE_WEIGHT, max(0.0, CPPI_MULTIPLIER * cushion))
        else:
            cycle_w = 0.0

        partner_w = 1.0 - cycle_w

        r = cycle_w * cycle_ret.loc[dt] + partner_w * partner_ret.loc[dt]
        nav = nav * (1 + r)

        # 如果组合触及/跌破 floor，关闭 CPPI，回到 Partner
        if nav <= floor:
            cppi_active = False
            cycle_w = 0.0
            partner_w = 1.0

        rows.append({
            "trade_date": dt,
            "portfolio_ret": r,
            "nav": nav,
            "peak_nav": peak,
            "floor_nav": floor,
            "cushion": cushion,
            "cycle_weight": cycle_w,
            "partner_weight": partner_w,
            "cppi_active": cppi_active,
            "reversal_signal": reversal,
            "position_252": signal.loc[dt, "position_252"],
            "three_day_return": signal.loc[dt, "three_day_return"],
        })

    return pd.DataFrame(rows).set_index("trade_date")


def main():
    close = pd.read_csv(CLOSE_PATH)
    returns = pd.read_csv(RETURNS_PATH)
    pairs = pd.read_csv(PAIRS_PATH)

    close["trade_date"] = pd.to_datetime(close["trade_date"])
    returns["trade_date"] = pd.to_datetime(returns["trade_date"])

    close = close.set_index("trade_date").sort_index()
    returns = returns.set_index("trade_date").sort_index()

    rank1_pairs = pairs[pairs["pair_rank"] == 1].sort_values("theme").drop_duplicates("theme")

    summary_rows = []
    nav_rows = []

    for _, p in rank1_pairs.iterrows():
        theme = p["theme"]
        cycle = p["cycle_ts_code"]
        partner = p["candidate_ts_code"]

        if cycle not in close.columns or cycle not in returns.columns or partner not in returns.columns:
            print("missing data:", theme, cycle, partner)
            continue

        strat = run_reversal_gated_cppi(
            cycle_ret=returns[cycle],
            partner_ret=returns[partner],
            close_series=close[cycle],
        )

        summary_rows.append({
            "theme": theme,
            "cycle_ts_code": cycle,
            "partner_ts_code": partner,
            "strategy": "REVERSAL_GATED_CPPI",
            "avg_cycle_weight": strat["cycle_weight"].mean(),
            "max_cycle_weight": strat["cycle_weight"].max(),
            "reversal_days": int(strat["reversal_signal"].sum()),
            "active_days": int(strat["cppi_active"].sum()),
            **metrics(strat["portfolio_ret"]),
        })

        for dt, r in strat.iterrows():
            nav_rows.append({
                "trade_date": dt,
                "theme": theme,
                "cycle_ts_code": cycle,
                "partner_ts_code": partner,
                "strategy": "REVERSAL_GATED_CPPI",
                "nav": r["nav"],
                "cycle_weight": r["cycle_weight"],
                "partner_weight": r["partner_weight"],
                "peak_nav": r["peak_nav"],
                "floor_nav": r["floor_nav"],
                "cushion": r["cushion"],
                "cppi_active": r["cppi_active"],
                "reversal_signal": r["reversal_signal"],
                "position_252": r["position_252"],
                "three_day_return": r["three_day_return"],
            })

    summary = pd.DataFrame(summary_rows)
    nav = pd.DataFrame(nav_rows)

    OUT_SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(OUT_SUMMARY, index=False, encoding="utf-8-sig")
    nav.to_csv(OUT_NAV, index=False, encoding="utf-8-sig")

    print("\n===== REVERSAL-GATED CPPI SUMMARY =====")
    print(summary.round(4).to_string(index=False))

    print("\nsaved:", OUT_SUMMARY)
    print("saved:", OUT_NAV)


if __name__ == "__main__":
    main()
