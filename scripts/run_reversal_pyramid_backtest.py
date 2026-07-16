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

OUT_SUMMARY = Path("data/processed/selection/reversal_pyramid_summary.csv")
OUT_NAV = Path("data/processed/selection/reversal_pyramid_nav.csv")
OUT_TRADES = Path("data/processed/selection/reversal_pyramid_trades.csv")

TRADING_DAYS = 252

LOW_POSITION_THRESHOLD = 0.30
THREE_DAY_RETURN_THRESHOLD = 0.05
THREE_DAY_VOLUME_RATIO_THRESHOLD = 1.30

ENTRY_WEIGHT = 0.10
ADD_WEIGHTS = [0.25, 0.45, 0.65, 0.80]
ADD_STEP = 0.10
STOP_LOSS = 0.10


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


def build_reversal_signals(close):
    df = close.copy()
    df["low_252"] = df["close"].rolling(252, min_periods=120).min()
    df["high_252"] = df["close"].rolling(252, min_periods=120).max()
    df["position_252"] = (df["close"] - df["low_252"]) / (df["high_252"] - df["low_252"])

    df["is_up_day"] = df["close"] > df["open"]
    df["three_up_days"] = (
        df["is_up_day"]
        & df["is_up_day"].shift(1)
        & df["is_up_day"].shift(2)
    )

    df["three_higher_close"] = (
        (df["close"] > df["close"].shift(1))
        & (df["close"].shift(1) > df["close"].shift(2))
    )

    df["three_day_return"] = df["close"] / df["close"].shift(3) - 1
    df["vol_ma20"] = df["vol"].rolling(20, min_periods=10).mean()
    df["three_day_vol_ratio"] = df["vol"].rolling(3).mean() / df["vol_ma20"]

    df["low_position_gate"] = df["position_252"].shift(3) <= LOW_POSITION_THRESHOLD

    df["reversal_trigger"] = (
        df["low_position_gate"]
        & df["three_up_days"]
        & df["three_higher_close"]
        & (df["three_day_return"] >= THREE_DAY_RETURN_THRESHOLD)
        & (df["three_day_vol_ratio"] >= THREE_DAY_VOLUME_RATIO_THRESHOLD)
    )

    return df


def run_pyramid_strategy(price_df, pair_ret, cycle_code, comp_code):
    sig = build_reversal_signals(price_df)

    common_index = pair_ret.index.intersection(sig.index)
    pair_ret = pair_ret.loc[common_index]
    sig = sig.loc[common_index]

    state = "WAIT"
    cycle_weight = 0.0
    add_level = -1
    last_add_price = np.nan

    rows = []
    trades = []

    for dt in common_index:
        close = float(sig.loc[dt, "close"])
        trigger = bool(sig.loc[dt, "reversal_trigger"])

        action = "HOLD"

        if state == "WAIT":
            cycle_weight = 0.0
            add_level = -1
            if trigger:
                state = "IN_POSITION"
                cycle_weight = ENTRY_WEIGHT
                add_level = 0
                last_add_price = close
                action = "ENTRY"

        elif state == "IN_POSITION":
            stop_price = last_add_price * (1 - STOP_LOSS)

            if close <= stop_price:
                action = "STOP_EXIT"
                state = "WAIT"
                cycle_weight = 0.0
                add_level = -1
                last_add_price = np.nan

            else:
                next_add_price = last_add_price * (1 + ADD_STEP)

                if close >= next_add_price and add_level < len(ADD_WEIGHTS):
                    cycle_weight = ADD_WEIGHTS[add_level]
                    last_add_price = close
                    add_level += 1
                    action = f"ADD_{add_level}"

        comp_weight = 1.0 - cycle_weight
        ret = cycle_weight * pair_ret.loc[dt, cycle_code] + comp_weight * pair_ret.loc[dt, comp_code]

        rows.append({
            "trade_date": dt,
            "portfolio_ret": ret,
            "cycle_weight": cycle_weight,
            "complement_weight": comp_weight,
            "state": state,
            "action": action,
            "close": close,
            "position_252": sig.loc[dt, "position_252"],
            "three_day_return": sig.loc[dt, "three_day_return"],
            "three_day_vol_ratio": sig.loc[dt, "three_day_vol_ratio"],
            "reversal_trigger": trigger,
        })

        if action != "HOLD":
            trades.append(rows[-1].copy())

    result = pd.DataFrame(rows).set_index("trade_date")
    result["nav"] = (1 + result["portfolio_ret"]).cumprod()
    trades = pd.DataFrame(trades)
    return result, trades


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
    trade_rows = []

    for _, p in rank1_pairs.iterrows():
        theme = p["theme"]
        cycle = p["cycle_ts_code"]
        comp = p["candidate_ts_code"]

        if cycle not in close.columns or cycle not in returns.columns or comp not in returns.columns:
            print("missing data:", theme, cycle, comp)
            continue

        # close matrix only has close price. For V1 we approximate open with previous close
        # and volume is unavailable in pair_close_matrix, so use price-derived pseudo volume check disabled if no vol.
        price_df = pd.DataFrame(index=close.index)
        price_df["close"] = close[cycle]
        price_df["open"] = close[cycle].shift(1)
        price_df["vol"] = 1.0

        # If no real volume exists, volume ratio would be 1 and trigger impossible.
        # Therefore V1 fallback uses price-only three soldiers.
        global THREE_DAY_VOLUME_RATIO_THRESHOLD
        old_threshold = THREE_DAY_VOLUME_RATIO_THRESHOLD
        THREE_DAY_VOLUME_RATIO_THRESHOLD = 0.90

        pair_ret = returns[[cycle, comp]].dropna()

        strat, trades = run_pyramid_strategy(price_df, pair_ret, cycle, comp)

        THREE_DAY_VOLUME_RATIO_THRESHOLD = old_threshold

        summary_rows.append({
            "theme": theme,
            "cycle_ts_code": cycle,
            "complement_ts_code": comp,
            "strategy": "REVERSAL_PYRAMID_PRICE_ONLY",
            "num_trades": len(trades),
            "avg_cycle_weight": strat["cycle_weight"].mean(),
            "max_cycle_weight": strat["cycle_weight"].max(),
            **metrics(strat["portfolio_ret"]),
        })

        nav_rows.extend(
            {
                "trade_date": d,
                "theme": theme,
                "strategy": "REVERSAL_PYRAMID_PRICE_ONLY",
                "nav": r["nav"],
                "cycle_weight": r["cycle_weight"],
                "complement_weight": r["complement_weight"],
                "state": r["state"],
                "action": r["action"],
            }
            for d, r in strat.iterrows()
        )

        if not trades.empty:
            trades["theme"] = theme
            trades["cycle_ts_code"] = cycle
            trades["complement_ts_code"] = comp
            trade_rows.append(trades)

    summary = pd.DataFrame(summary_rows)
    nav = pd.DataFrame(nav_rows)
    trades = pd.concat(trade_rows, ignore_index=True) if trade_rows else pd.DataFrame()

    OUT_SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(OUT_SUMMARY, index=False, encoding="utf-8-sig")
    nav.to_csv(OUT_NAV, index=False, encoding="utf-8-sig")
    trades.to_csv(OUT_TRADES, index=False, encoding="utf-8-sig")

    print("\n===== REVERSAL PYRAMID SUMMARY =====")
    print(summary.round(4).to_string(index=False))

    print("\nsaved:", OUT_SUMMARY)
    print("saved:", OUT_NAV)
    print("saved:", OUT_TRADES)

    if trades.empty:
        print("\nNo trades generated. Need real OHLCV data for strict bottom-volume confirmation.")
    else:
        print("\n===== TRADES SAMPLE =====")
        print(trades.head(30).to_string(index=False))


if __name__ == "__main__":
    main()
