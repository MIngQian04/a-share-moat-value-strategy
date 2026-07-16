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

OUT_SUMMARY = Path("data/processed/selection/defensive_anchor_cppi_summary.csv")
OUT_NAV = Path("data/processed/selection/defensive_anchor_cppi_nav.csv")

TRADING_DAYS = 252

ANCHORS = ["600519.SH", "600900.SH"]
RISK_FREE_RATE = 0.015
RISK_FREE_DAILY = (1 + RISK_FREE_RATE) ** (1 / TRADING_DAYS) - 1

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


def choose_anchor_for_cycle(cycle_code, returns):
    candidates = []

    for anchor in ANCHORS:
        if anchor not in returns.columns:
            continue

        pair = returns[[cycle_code, anchor]].dropna()

        if pair.empty:
            continue

        cycle_ret = pair[cycle_code]
        anchor_ret = pair[anchor]

        stress_mask = cycle_ret <= cycle_ret.quantile(0.20)

        downside_corr = cycle_ret[stress_mask].corr(anchor_ret[stress_mask])
        stress_return = anchor_ret[stress_mask].mean()

        anchor_nav = (1 + anchor_ret).cumprod()
        anchor_dd = anchor_nav / anchor_nav.cummax() - 1
        anchor_max_dd = anchor_dd.min()
        anchor_ann_vol = anchor_ret.std() * np.sqrt(TRADING_DAYS)
        anchor_ann_return = annual_return(anchor_ret)

        score = 0

        if pd.notna(downside_corr):
            score += (1 - max(min(downside_corr, 1), -1)) * 30

        score += max(min((stress_return + 0.01) / 0.02, 1), 0) * 30

        score += max(min((0.60 + anchor_max_dd) / 0.60, 1), 0) * 20

        score += max(min((0.35 - anchor_ann_vol) / 0.35, 1), 0) * 20

        candidates.append({
            "anchor": anchor,
            "anchor_score": score,
            "downside_corr": downside_corr,
            "stress_return": stress_return,
            "anchor_max_drawdown": anchor_max_dd,
            "anchor_ann_vol": anchor_ann_vol,
            "anchor_ann_return": anchor_ann_return,
        })

    if not candidates:
        return None

    return sorted(candidates, key=lambda x: x["anchor_score"], reverse=True)[0]


def run_anchor_cppi(cycle_ret, anchor_ret, close_series):
    signal = build_price_reversal_signal(close_series)

    rf = pd.Series(RISK_FREE_DAILY, index=cycle_ret.index, name="risk_free")

    common = (
        cycle_ret.dropna().index
        .intersection(anchor_ret.dropna().index)
        .intersection(signal.index)
        .intersection(rf.index)
    )

    cycle_ret = cycle_ret.loc[common]
    anchor_ret = anchor_ret.loc[common]
    rf = rf.loc[common]
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

        defensive_w = 1.0 - cycle_w

        # Defensive sleeve: anchor + risk-free
        # V1 simple rule:
        # if anchor is above its 252d low-position stress zone, use anchor;
        # otherwise split anchor/risk-free 50/50.
        anchor_position = signal.loc[dt, "position_252"]

        if pd.notna(anchor_position) and anchor_position <= 0.20:
            anchor_w_inside_defensive = 0.50
        else:
            anchor_w_inside_defensive = 0.80

        anchor_w = defensive_w * anchor_w_inside_defensive
        rf_w = defensive_w * (1 - anchor_w_inside_defensive)

        r = (
            cycle_w * cycle_ret.loc[dt]
            + anchor_w * anchor_ret.loc[dt]
            + rf_w * rf.loc[dt]
        )

        nav = nav * (1 + r)

        if nav <= floor:
            cppi_active = False

        rows.append({
            "trade_date": dt,
            "portfolio_ret": r,
            "nav": nav,
            "peak_nav": peak,
            "floor_nav": floor,
            "cushion": cushion,
            "cycle_weight": cycle_w,
            "anchor_weight": anchor_w,
            "risk_free_weight": rf_w,
            "defensive_weight": defensive_w,
            "cppi_active": cppi_active,
            "reversal_signal": reversal,
            "cycle_position_252": signal.loc[dt, "position_252"],
            "cycle_three_day_return": signal.loc[dt, "three_day_return"],
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

    rank1_cycles = (
        pairs[["theme", "cycle_ts_code"]]
        .drop_duplicates()
        .sort_values("theme")
    )

    summary_rows = []
    nav_rows = []

    for _, row in rank1_cycles.iterrows():
        theme = row["theme"]
        cycle = row["cycle_ts_code"]

        if cycle not in close.columns or cycle not in returns.columns:
            print("missing cycle data:", theme, cycle)
            continue

        anchor_info = choose_anchor_for_cycle(cycle, returns)

        if anchor_info is None:
            print("missing anchor data:", theme, cycle)
            continue

        anchor = anchor_info["anchor"]

        strat = run_anchor_cppi(
            cycle_ret=returns[cycle],
            anchor_ret=returns[anchor],
            close_series=close[cycle],
        )

        summary_rows.append({
            "theme": theme,
            "cycle_ts_code": cycle,
            "anchor_ts_code": anchor,
            "strategy": "DEFENSIVE_ANCHOR_CPPI",
            "avg_cycle_weight": strat["cycle_weight"].mean(),
            "max_cycle_weight": strat["cycle_weight"].max(),
            "avg_anchor_weight": strat["anchor_weight"].mean(),
            "avg_risk_free_weight": strat["risk_free_weight"].mean(),
            "reversal_days": int(strat["reversal_signal"].sum()),
            "active_days": int(strat["cppi_active"].sum()),
            **anchor_info,
            **metrics(strat["portfolio_ret"]),
        })

        for dt, r in strat.iterrows():
            nav_rows.append({
                "trade_date": dt,
                "theme": theme,
                "cycle_ts_code": cycle,
                "anchor_ts_code": anchor,
                "strategy": "DEFENSIVE_ANCHOR_CPPI",
                "nav": r["nav"],
                "cycle_weight": r["cycle_weight"],
                "anchor_weight": r["anchor_weight"],
                "risk_free_weight": r["risk_free_weight"],
                "defensive_weight": r["defensive_weight"],
                "peak_nav": r["peak_nav"],
                "floor_nav": r["floor_nav"],
                "cushion": r["cushion"],
                "cppi_active": r["cppi_active"],
                "reversal_signal": r["reversal_signal"],
            })

    summary = pd.DataFrame(summary_rows)
    nav = pd.DataFrame(nav_rows)

    OUT_SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(OUT_SUMMARY, index=False, encoding="utf-8-sig")
    nav.to_csv(OUT_NAV, index=False, encoding="utf-8-sig")

    print("\n===== DEFENSIVE ANCHOR CPPI SUMMARY =====")
    cols = [
        "theme", "cycle_ts_code", "anchor_ts_code",
        "avg_cycle_weight", "max_cycle_weight",
        "avg_anchor_weight", "avg_risk_free_weight",
        "annual_return", "annual_vol", "sharpe",
        "sortino", "max_drawdown", "calmar",
        "final_nav", "reversal_days", "active_days",
        "anchor_score", "downside_corr", "stress_return",
        "anchor_max_drawdown", "anchor_ann_vol",
        "anchor_ann_return",
    ]
    cols = [c for c in cols if c in summary.columns]
    print(summary[cols].round(4).to_string(index=False))

    print("\nsaved:", OUT_SUMMARY)
    print("saved:", OUT_NAV)


if __name__ == "__main__":
    main()
