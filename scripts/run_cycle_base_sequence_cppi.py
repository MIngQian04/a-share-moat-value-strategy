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

from brake.sell_side_brake import SellSideBrakeEngine

REGIME_PATH = Path("data/processed/selection/theme_proxy_regime_history.csv")
PROXY_RETURNS_PATH = Path("data/processed/research/theme_proxy_returns.parquet")
STOCK_RETURNS_PATH = Path("data/processed/selection/stock_return_matrix.csv")

OPEN = Path("data/processed/research/rank1_open.parquet")
HIGH = Path("data/processed/research/rank1_high.parquet")
LOW = Path("data/processed/research/rank1_low.parquet")
CLOSE = Path("data/processed/research/rank1_close.parquet")
AMOUNT = Path("data/processed/research/rank1_amount.parquet")

OUT_SUMMARY = Path("data/processed/selection/cycle_base_sequence_cppi_summary.csv")
OUT_NAV = Path("data/processed/selection/cycle_base_sequence_cppi_nav.csv")
OUT_TRADES = Path("data/processed/selection/cycle_base_sequence_cppi_trades.csv")

TRADING_DAYS = 252
ANCHOR_CODE = "600900.SH"
RISK_FREE_RATE = 0.015
RISK_FREE_DAILY = (1 + RISK_FREE_RATE) ** (1 / TRADING_DAYS) - 1

ANCHOR_DEFENSIVE_WEIGHT = 0.80

BASE_WEIGHT_BY_THEME = {
    "lithium": 0.20,
    "copper": 0.15,
    "coal": 0.15,
    "oil": 0.15,
    "solar": 0.15,
    "steel": 0.10,
    "fertilizer": 0.00,
}

MAX_CYCLE_WEIGHT = 0.60
MAX_DRAWDOWN_LIMIT = 0.20
CPPI_MULTIPLIER = 3.0

LOW_POSITION_THRESHOLD = 0.35
AMOUNT_RATIO_THRESHOLD = 1.50
LOOKAHEAD_DAYS = 25
INVALIDATION_DROP = -0.05
THREE_DAY_GAIN_THRESHOLD = 0.05

EXPANSION_TRAILING_STOP = 0.10

# Sell-side brake caps existing CPPI/step-add exposure.
# It never creates a buy/add signal.
BRAKE_EARLY_CAP = 0.45   # top-volume stagnation: harvest partial profit
BRAKE_TREND_CAP = 0.25   # close below MA20: reduce to observation exposure
BRAKE_FULL_CAP = 0.00    # close below MA40: exit cycle sleeve

# Post-brake re-expansion gate.
# Normal first expansion / step-add is untouched.
# This gate only applies after a SELL_SIDE_BRAKE has already fired.
ALLOW_REEXPANSION_REGIMES = {
    "BOTTOM_RECOVERY",
    "EARLY_STABILIZING",
    "STABILIZING",
    "EXPANSION",
}

BLOCK_REEXPANSION_REGIMES = {
    "NEUTRAL",
    "CONTRACTION",
    "LATE_CYCLE",
    "DEEP_BOTTOM_FALLING",
    "UNKNOWN",
}


def stage_allows_reexpansion(regime: str | None) -> bool:
    if regime is None:
        return False
    return str(regime) in ALLOW_REEXPANSION_REGIMES



def get_current_theme_regime(regime_table: pd.DataFrame, dt, theme: str | None) -> str | None:
    if theme is None:
        return None
    key = (dt, theme)
    if key not in regime_table.index:
        return None
    value = regime_table.loc[key, "theme_regime"]
    if pd.isna(value):
        return None
    return str(value)



def metrics(ret):
    ret = pd.Series(ret).dropna()
    nav = (1 + ret).cumprod()
    ar = nav.iloc[-1] ** (TRADING_DAYS / len(ret)) - 1
    vol = ret.std() * np.sqrt(TRADING_DAYS)
    sharpe = ((ret - RISK_FREE_DAILY).mean() / ret.std() * np.sqrt(TRADING_DAYS)) if ret.std() > 0 else np.nan
    downside = ret[ret < 0].std()
    sortino = ((ret - RISK_FREE_DAILY).mean() / downside * np.sqrt(TRADING_DAYS)) if pd.notna(downside) and downside > 0 else np.nan
    dd = (nav / nav.cummax() - 1).min()
    return {
        "n_obs": len(ret),
        "annual_return": ar,
        "annual_vol": vol,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": dd,
        "calmar": ar / abs(dd) if dd < 0 else np.nan,
        "final_nav": nav.iloc[-1],
    }


def three_soldiers_after_volume(open_, high, low, close):
    bullish = close > open_
    higher_close = (close > close.shift(1)) & (close.shift(1) > close.shift(2))
    gain3 = close / close.shift(3) - 1
    body = (close - open_).abs()
    range_ = (high - low).replace(0, np.nan)
    solid_body = (body / range_ >= 0.35)
    return (
        bullish
        & bullish.shift(1)
        & bullish.shift(2)
        & higher_close
        & (gain3 >= THREE_DAY_GAIN_THRESHOLD)
        & solid_body
        & solid_body.shift(1)
        & solid_body.shift(2)
    )


def main():
    regime = pd.read_csv(REGIME_PATH)
    regime["trade_date"] = pd.to_datetime(regime["trade_date"])
    regime = regime.set_index(["trade_date", "theme"]).sort_index()

    proxy = pd.read_parquet(PROXY_RETURNS_PATH)
    proxy.index = pd.to_datetime(proxy.index)

    stock_ret = pd.read_csv(STOCK_RETURNS_PATH)
    stock_ret["trade_date"] = pd.to_datetime(stock_ret["trade_date"])
    stock_ret = stock_ret.set_index("trade_date").sort_index()

    open_df = pd.read_parquet(OPEN)
    high_df = pd.read_parquet(HIGH)
    low_df = pd.read_parquet(LOW)
    close_df = pd.read_parquet(CLOSE)
    amount_df = pd.read_parquet(AMOUNT)

    brake_engine = SellSideBrakeEngine(
        compression_spread=0.03,
        compression_cap=BRAKE_EARLY_CAP,
        compression_warning_cap=0.35,
        trend_cap=BRAKE_TREND_CAP,
        full_cap=BRAKE_FULL_CAP,
    )
    last_brake_state = "DISABLED"
    trend_armed = False
    post_brake = False

    anchor_ret = pd.to_numeric(stock_ret[ANCHOR_CODE], errors="coerce")
    dates = proxy.index.intersection(anchor_ret.dropna().index).sort_values()

    nav = 1.0
    peak_nav = 1.0

    current_theme = None
    base_weight = 0.0
    risk_expansion_open = False

    step_weight = 0.0
    last_add_price = np.nan
    expansion_peak_price = np.nan

    volume_state = "NONE"
    volume_event_date = None
    volume_event_low = np.nan
    days_after_volume = 0

    # Signals are observed at the close.  They become executable only for the
    # following session; keeping a separate executed sleeve prevents same-day
    # close-to-close look-ahead in the NAV calculation.
    executed_theme = None
    executed_cycle_weight = 0.0
    executed_anchor_weight = ANCHOR_DEFENSIVE_WEIGHT
    executed_rf_weight = 1.0 - ANCHOR_DEFENSIVE_WEIGHT

    rows = []
    trades = []

    for dt in dates:
        current_theme_regime = get_current_theme_regime(regime, dt, current_theme)

        # ENTRY: only when no current theme
        if current_theme is None:
            candidates = []
            for theme in proxy.columns:
                key = (dt, theme)
                if key not in regime.index:
                    continue
                r = regime.loc[key]
                if bool(r["entry_eligible"]):
                    bw = BASE_WEIGHT_BY_THEME.get(theme, 0.0)
                    if bw > 0:
                        candidates.append({
                            "theme": theme,
                            "score": r["theme_opportunity_score"],
                            "base_weight": bw,
                            "regime": r["theme_regime"],
                        })

            if candidates:
                chosen = pd.DataFrame(candidates).sort_values(["score", "base_weight"], ascending=[False, False]).iloc[0]
                current_theme = chosen["theme"]
                base_weight = float(chosen["base_weight"])
                risk_expansion_open = False
                step_weight = base_weight
                last_add_price = np.nan
                expansion_peak_price = np.nan
                volume_state = "NONE"
                volume_event_date = None
                volume_event_low = np.nan
                days_after_volume = 0
                trend_armed = False
                last_brake_state = "DISABLED"
                post_brake = False

                trades.append({
                    "trade_date": dt,
                    "action": "ENTER_BASE",
                    "theme": current_theme,
                    "cycle_weight": base_weight,
                    "score": chosen["score"],
                    "regime": chosen["regime"],
                    "nav": nav,
                })

        # EXIT
        if current_theme is not None:
            key = (dt, current_theme)
            if key in regime.index and bool(regime.loc[key, "exit_signal"]):
                trades.append({
                    "trade_date": dt,
                    "action": "EXIT_THEME",
                    "theme": current_theme,
                    "cycle_weight": 0.0,
                    "regime": regime.loc[key, "theme_regime"],
                    "nav": nav,
                })
                current_theme = None
                base_weight = 0.0
                risk_expansion_open = False
                step_weight = 0.0
                last_add_price = np.nan
                expansion_peak_price = np.nan
                volume_state = "NONE"
                volume_event_date = None
                volume_event_low = np.nan
                days_after_volume = 0
                trend_armed = False
                last_brake_state = "DISABLED"
                post_brake = False

        # Sequence detection while holding base
        if current_theme is not None and not risk_expansion_open:
            close = close_df[current_theme]
            open_ = open_df[current_theme]
            high = high_df[current_theme]
            low = low_df[current_theme]
            amount = amount_df[current_theme]

            if dt in close.index and pd.notna(close.loc[dt]):
                nav_theme = close / close.dropna().iloc[0]
                low252 = nav_theme.rolling(252, min_periods=120).min()
                high252 = nav_theme.rolling(252, min_periods=120).max()
                pos252 = (nav_theme - low252) / (high252 - low252)

                amount_ratio = amount.rolling(5).mean() / amount.rolling(60).mean()
                bottom_volume = (
                    pd.notna(pos252.loc[dt])
                    and pos252.loc[dt] <= LOW_POSITION_THRESHOLD
                    and pd.notna(amount_ratio.loc[dt])
                    and amount_ratio.loc[dt] >= AMOUNT_RATIO_THRESHOLD
                )

                soldiers = three_soldiers_after_volume(open_, high, low, close)

                if volume_state == "NONE" and bottom_volume:
                    volume_state = "VOLUME_DETECTED"
                    volume_event_date = dt
                    volume_event_low = float(low.loc[dt])
                    days_after_volume = 0
                    trades.append({
                        "trade_date": dt,
                        "action": "BOTTOM_VOLUME",
                        "theme": current_theme,
                        "amount_ratio": amount_ratio.loc[dt],
                        "position_252": pos252.loc[dt],
                        "nav": nav,
                    })

                elif volume_state == "VOLUME_DETECTED":
                    days_after_volume += 1

                    if low.loc[dt] < volume_event_low * (1 + INVALIDATION_DROP):
                        trades.append({
                            "trade_date": dt,
                            "action": "VOLUME_INVALIDATED",
                            "theme": current_theme,
                            "nav": nav,
                        })
                        volume_state = "NONE"
                        volume_event_date = None
                        volume_event_low = np.nan
                        days_after_volume = 0

                    elif days_after_volume > LOOKAHEAD_DAYS:
                        # Time-survived accumulation confirmation:
                        # bottom volume survived the observation window
                        # without invalidation, so open step-up permission.
                        risk_expansion_open = True
                        volume_state = "ACCUMULATION_CONFIRMED"

                        step_weight = base_weight
                        last_add_price = float(close.loc[dt])
                        expansion_peak_price = float(close.loc[dt])

                        volume_close = float(close.loc[volume_event_date])
                        current_close = float(close.loc[dt])

                        trades.append({
                            "trade_date": dt,
                            "action": "TIME_SURVIVED_ACCUMULATION_CONFIRMED",
                            "theme": current_theme,
                            "days_after_volume": days_after_volume,
                            "cycle_weight": step_weight,
                            "last_add_price": last_add_price,
                            "gain_from_volume": current_close / volume_close - 1.0,
                            "confirm_reasons": "TIME_SURVIVED",
                            "nav": nav,
                        })

                    elif bool(soldiers.loc[dt]):
                        # Important: three soldiers must all be after volume event
                        locs = close.index
                        i = locs.get_loc(dt)
                        soldier_start = locs[i - 2]
                        if soldier_start > volume_event_date:
                            risk_expansion_open = True
                            volume_state = "CONFIRMED"

                            step_weight = base_weight
                            last_add_price = float(close.loc[dt])
                            expansion_peak_price = float(close.loc[dt])

                            trades.append({
                                "trade_date": dt,
                                "action": "SEQUENCE_CONFIRMED_OPEN_STEP_RISK",
                                "theme": current_theme,
                                "days_after_volume": days_after_volume,
                                "cycle_weight": step_weight,
                                "last_add_price": last_add_price,
                                "nav": nav,
                            })

        # CPPI risk scaling
        peak_nav = max(peak_nav, nav)
        floor_nav = peak_nav * (1 - MAX_DRAWDOWN_LIMIT)
        cushion = max((nav - floor_nav) / nav, 0.0)
        cppi_weight = min(MAX_CYCLE_WEIGHT, CPPI_MULTIPLIER * cushion)

        if current_theme is None:
            cycle_weight = 0.0

        elif risk_expansion_open:
            current_price = close_df[current_theme].loc[dt]

            if pd.notna(current_price):
                current_price = float(current_price)

                if pd.isna(expansion_peak_price):
                    expansion_peak_price = current_price

                expansion_peak_price = max(expansion_peak_price, current_price)

                if (
                    expansion_peak_price > 0
                    and current_price <= expansion_peak_price * (1.0 - EXPANSION_TRAILING_STOP)
                ):
                    trades.append({
                        "trade_date": dt,
                        "action": "DROP_EXPANSION_TO_BASE",
                        "theme": current_theme,
                        "expansion_peak_price": expansion_peak_price,
                        "current_price": current_price,
                        "drawdown_from_expansion_peak": current_price / expansion_peak_price - 1.0,
                        "old_step_weight": step_weight,
                        "new_weight": base_weight,
                        "nav": nav,
                    })

                    risk_expansion_open = False
                    step_weight = base_weight
                    last_add_price = np.nan
                    expansion_peak_price = np.nan
                    volume_state = "NONE"

                elif pd.notna(last_add_price) and last_add_price > 0:
                    reexpansion_allowed = (
                        (not post_brake)
                        or stage_allows_reexpansion(current_theme_regime)
                    )

                    if reexpansion_allowed:
                        while (
                            current_price >= last_add_price * 1.10
                            and step_weight < MAX_CYCLE_WEIGHT
                        ):
                            old_weight = step_weight
                            step_weight = min(MAX_CYCLE_WEIGHT, step_weight + 0.10)
                            last_add_price = last_add_price * 1.10

                            trades.append({
                                "trade_date": dt,
                                "action": "STEP_ADD",
                                "theme": current_theme,
                                "regime": current_theme_regime,
                                "post_brake": post_brake,
                                "old_weight": old_weight,
                                "new_weight": step_weight,
                                "last_add_price": last_add_price,
                                "current_price": current_price,
                                "cppi_ceiling": cppi_weight,
                                "nav": nav,
                            })
                    elif current_price >= last_add_price * 1.10 and step_weight < MAX_CYCLE_WEIGHT:
                        trades.append({
                            "trade_date": dt,
                            "action": "STEP_ADD_BLOCKED_POST_BRAKE_STAGE",
                            "theme": current_theme,
                            "regime": current_theme_regime,
                            "post_brake": post_brake,
                            "old_weight": step_weight,
                            "new_weight": step_weight,
                            "last_add_price": last_add_price,
                            "current_price": current_price,
                            "cppi_ceiling": cppi_weight,
                            "nav": nav,
                        })

            if risk_expansion_open:
                cycle_weight = min(step_weight, cppi_weight, MAX_CYCLE_WEIGHT)
                cycle_weight = max(base_weight, cycle_weight)
            else:
                cycle_weight = base_weight

        else:
            cycle_weight = base_weight

        # ============================================================
        # SELL-SIDE BRAKE ENGINE v2 — TREND ARMED
        # Existing accumulation / CPPI / step-add logic is unchanged.
        # ============================================================
        raw_cycle_weight = cycle_weight
        brake_state = "DISABLED"
        brake_reason = "NO_POSITION"
        brake_cap = 1.0
        brake_current_price = np.nan
        brake_ma5 = np.nan
        brake_ma20 = np.nan
        brake_ma40 = np.nan
        brake_ma_spread = np.nan
        brake_amount_ratio_5_20 = np.nan
        brake_ret5 = np.nan
        brake_distribution_warning = False

        if current_theme is not None:
            brake = brake_engine.evaluate_until(
                dt, current_theme, close_df, amount_df,
                trend_armed_prev=trend_armed,
            )
            trend_armed = brake.trend_armed
            brake_state = brake.brake_state
            brake_reason = brake.brake_reason
            brake_cap = brake.brake_cap
            brake_current_price = brake.current_price
            brake_ma5 = brake.ma5
            brake_ma20 = brake.ma20
            brake_ma40 = brake.ma40
            brake_ma_spread = brake.ma_spread
            brake_amount_ratio_5_20 = brake.amount_ratio_5_20
            brake_ret5 = brake.ret5
            brake_distribution_warning = brake.distribution_warning

            cycle_weight = brake_engine.apply_cap(raw_cycle_weight, brake_cap)

            if brake_state in ["TREND_BRAKE", "FULL_BRAKE"] and cycle_weight < raw_cycle_weight:
                post_brake = True

            if cycle_weight < raw_cycle_weight and brake_state != last_brake_state:
                trades.append({
                    "trade_date": dt,
                    "action": "SELL_SIDE_BRAKE",
                    "theme": current_theme,
                    "brake_state": brake_state,
                    "brake_reason": brake_reason,
                    "old_weight": raw_cycle_weight,
                    "new_weight": cycle_weight,
                    "brake_cap": brake_cap,
                    "trend_armed": trend_armed,
            "post_brake": post_brake,
                    "post_brake": post_brake,
                    "current_price": brake_current_price,
                    "ma5": brake_ma5,
                    "ma20": brake_ma20,
                    "ma40": brake_ma40,
                    "ma_spread": brake_ma_spread,
                    "amount_ratio_5_20": brake_amount_ratio_5_20,
                    "ret5": brake_ret5,
                    "distribution_warning": brake_distribution_warning,
                    "nav": nav,
                })
            last_brake_state = brake_state
        else:
            trend_armed = False
            last_brake_state = "DISABLED"
            post_brake = False

        defensive_weight = 1.0 - cycle_weight
        anchor_weight = defensive_weight * ANCHOR_DEFENSIVE_WEIGHT
        rf_weight = defensive_weight * (1 - ANCHOR_DEFENSIVE_WEIGHT)

        # ============================================================
        # PORTFOLIO ACCOUNTING
        #
        # Missing return handling:
        # A missing asset return must NEVER poison the entire NAV path.
        #
        # If a held asset has no return observation on a trading date,
        # treat that sleeve as 0% return for that date.
        #
        # We also explicitly record missing-return events for audit.
        # ============================================================

        anchor_r = anchor_ret.loc[dt]

        anchor_missing = pd.isna(anchor_r)

        if anchor_missing:
            anchor_r = 0.0
        else:
            anchor_r = float(anchor_r)

        cycle_r = 0.0
        cycle_missing = False

        if executed_theme is not None:
            raw_cycle_r = proxy.loc[dt, executed_theme]

            if pd.isna(raw_cycle_r):
                cycle_missing = True
                cycle_r = 0.0
            else:
                cycle_r = float(raw_cycle_r)

        ret = (
            executed_anchor_weight * anchor_r
            + executed_rf_weight * RISK_FREE_DAILY
            + executed_cycle_weight * cycle_r
        )

        if not np.isfinite(ret):
            raise ValueError(
                f"Non-finite portfolio return at {dt}: "
                f"executed_theme={executed_theme}, "
                f"executed_cycle_weight={executed_cycle_weight}, "
                f"executed_anchor_weight={executed_anchor_weight}, "
                f"executed_rf_weight={executed_rf_weight}, "
                f"anchor_r={anchor_r}, "
                f"cycle_r={cycle_r}"
            )

        nav *= 1.0 + ret

        if not np.isfinite(nav):
            raise ValueError(
                f"NAV became non-finite at {dt}: "
                f"ret={ret}, executed_theme={executed_theme}"
            )

        rows.append({
            "trade_date": dt,
            "portfolio_ret": ret,
            "nav": nav,
            "peak_nav": peak_nav,
            "floor_nav": floor_nav,
            "cushion": cushion,
            "current_theme": current_theme,
            "base_weight": base_weight,
            "risk_expansion_open": risk_expansion_open,
            "raw_cycle_weight_before_brake": raw_cycle_weight,
            "cycle_weight": cycle_weight,
            "brake_state": brake_state,
            "brake_reason": brake_reason,
            "brake_cap": brake_cap,
            "trend_armed": trend_armed,
            "post_brake": post_brake,
            "brake_current_price": brake_current_price,
            "brake_ma5": brake_ma5,
            "brake_ma20": brake_ma20,
            "brake_ma40": brake_ma40,
            "brake_ma_spread": brake_ma_spread,
            "brake_amount_ratio_5_20": brake_amount_ratio_5_20,
            "brake_ret5": brake_ret5,
            "brake_distribution_warning": brake_distribution_warning,
            "anchor_weight": anchor_weight,
            "risk_free_weight": rf_weight,
            "volume_state": volume_state,
            "anchor_return_missing": anchor_missing,
            "cycle_return_missing": cycle_missing,
            "anchor_return_used": anchor_r,
            "cycle_return_used": cycle_r,
            "executed_theme": executed_theme,
            "executed_cycle_weight": executed_cycle_weight,
            "executed_anchor_weight": executed_anchor_weight,
            "executed_risk_free_weight": executed_rf_weight,
        })

        # Submit today's close-based target for execution on the next session.
        executed_theme = current_theme
        executed_cycle_weight = cycle_weight
        executed_anchor_weight = anchor_weight
        executed_rf_weight = rf_weight

    nav_df = pd.DataFrame(rows)
    trades_df = pd.DataFrame(trades)

    summary = pd.DataFrame([{
        "strategy": "BASE_TIME_SURVIVED_ACCUM_STEP_UP_CPPI_SELL_SIDE_BRAKE_V2_3_1_REGIME_FIX",
        "avg_cycle_weight": nav_df["cycle_weight"].mean(),
        "max_cycle_weight": nav_df["cycle_weight"].max(),
        "avg_anchor_weight": nav_df["anchor_weight"].mean(),
        "avg_risk_free_weight": nav_df["risk_free_weight"].mean(),
        "num_base_entries": int((trades_df["action"] == "ENTER_BASE").sum()) if not trades_df.empty else 0,
        "num_sequence_confirms": int((trades_df["action"].isin(["SEQUENCE_CONFIRMED_OPEN_STEP_RISK", "TIME_SURVIVED_ACCUMULATION_CONFIRMED"])).sum()) if not trades_df.empty else 0,
        "num_step_adds": int((trades_df["action"] == "STEP_ADD").sum()) if not trades_df.empty else 0,
        "num_drop_expansion": int((trades_df["action"] == "DROP_EXPANSION_TO_BASE").sum()) if not trades_df.empty else 0,
        "num_sell_side_brakes": int((trades_df["action"] == "SELL_SIDE_BRAKE").sum()) if not trades_df.empty else 0,
        "num_step_add_blocked_post_brake_stage": int((trades_df["action"] == "STEP_ADD_BLOCKED_POST_BRAKE_STAGE").sum()) if not trades_df.empty else 0,
        "brake_days": int((nav_df["brake_state"].isin(["COMPRESSION_BRAKE", "TREND_BRAKE", "FULL_BRAKE"])).sum()) if not nav_df.empty else 0,
        **metrics(nav_df["portfolio_ret"]),
    }])

    OUT_SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(OUT_SUMMARY, index=False, encoding="utf-8-sig")
    nav_df.to_csv(OUT_NAV, index=False, encoding="utf-8-sig")
    trades_df.to_csv(OUT_TRADES, index=False, encoding="utf-8-sig")

    print("\n===== BASE + SEQUENCE + STEP-UP + CPPI + SELL-SIDE BRAKE SUMMARY =====")
    print(summary.round(4).to_string(index=False))

    print("\n===== TRADES =====")
    print(trades_df.round(4).to_string(index=False) if not trades_df.empty else "NO TRADES")

    print("\n===== HOLDING DAYS =====")
    print(nav_df["current_theme"].value_counts(dropna=False).to_string())

    print("\nsaved:", OUT_SUMMARY)
    print("saved:", OUT_NAV)
    print("saved:", OUT_TRADES)


if __name__ == "__main__":
    main()
