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

REGIME_PATH = Path("data/processed/selection/theme_proxy_regime_history.csv")
PROXY_RETURNS_PATH = Path("data/processed/research/theme_proxy_returns.parquet")
STOCK_RETURNS_PATH = Path("data/processed/selection/stock_return_matrix.csv")

OUT_SUMMARY = Path("data/processed/selection/single_theme_profile_summary.csv")
OUT_NAV = Path("data/processed/selection/single_theme_profile_nav.csv")
OUT_TRADES = Path("data/processed/selection/single_theme_profile_trades.csv")

TRADING_DAYS = 252

ANCHOR_CODE = "600900.SH"
RISK_FREE_RATE = 0.015
RISK_FREE_DAILY = (1 + RISK_FREE_RATE) ** (1 / TRADING_DAYS) - 1

ANCHOR_DEFENSIVE_WEIGHT = 0.80

# ============================================================
# Theme Base Entry Profile
# ============================================================

BASE_WEIGHT_BY_THEME = {
    "lithium": 0.20,
    "copper": 0.15,
    "coal": 0.15,
    "oil": 0.15,
    "solar": 0.15,
    "steel": 0.10,
    "fertilizer": 0.00,
}

PROFILE_BY_THEME = {
    "lithium": "AGGRESSIVE_BASE",
    "copper": "NORMAL_BASE",
    "coal": "NORMAL_BASE",
    "oil": "NORMAL_BASE",
    "solar": "NORMAL_BASE",
    "steel": "PATIENT_BASE",
    "fertilizer": "CONFIRMATION_REQUIRED",
}


def max_drawdown(ret):
    nav = (1 + ret).cumprod()
    return float((nav / nav.cummax() - 1).min())


def annual_return(ret):
    ret = ret.dropna()
    if ret.empty:
        return np.nan
    nav = float((1 + ret).prod())
    years = len(ret) / TRADING_DAYS
    return nav ** (1 / years) - 1 if nav > 0 and years > 0 else np.nan


def annual_vol(ret):
    return float(ret.dropna().std() * np.sqrt(TRADING_DAYS))


def sharpe(ret):
    ret = ret.dropna()
    excess = ret - RISK_FREE_DAILY
    sd = excess.std()
    return float(excess.mean() / sd * np.sqrt(TRADING_DAYS)) if sd and not pd.isna(sd) else np.nan


def sortino(ret):
    ret = ret.dropna()
    excess = ret - RISK_FREE_DAILY
    downside = excess[excess < 0]
    sd = downside.std()
    return float(excess.mean() / sd * np.sqrt(TRADING_DAYS)) if sd and not pd.isna(sd) else np.nan


def metrics(ret):
    ret = pd.Series(ret).dropna()
    dd = max_drawdown(ret)
    ar = annual_return(ret)
    return {
        "n_obs": len(ret),
        "annual_return": ar,
        "annual_vol": annual_vol(ret),
        "sharpe": sharpe(ret),
        "sortino": sortino(ret),
        "max_drawdown": dd,
        "calmar": ar / abs(dd) if dd < 0 else np.nan,
        "final_nav": float((1 + ret).prod()),
    }


def main():
    regime = pd.read_csv(REGIME_PATH)
    regime["trade_date"] = pd.to_datetime(regime["trade_date"])

    proxy = pd.read_parquet(PROXY_RETURNS_PATH)
    proxy.index = pd.to_datetime(proxy.index)

    stock_ret = pd.read_csv(STOCK_RETURNS_PATH)
    stock_ret["trade_date"] = pd.to_datetime(stock_ret["trade_date"])
    stock_ret = stock_ret.set_index("trade_date").sort_index()

    anchor_ret = pd.to_numeric(stock_ret[ANCHOR_CODE], errors="coerce")

    dates = proxy.index.intersection(anchor_ret.dropna().index).sort_values()

    regime_today = (
        regime
        .set_index(["trade_date", "theme"])
        .sort_index()
    )

    current_theme = None
    current_weight = 0.0
    current_profile = None

    nav = 1.0
    rows = []
    trades = []

    for dt in dates:
        # ====================================================
        # If no current theme, scan entry candidates
        # ====================================================
        if current_theme is None:
            day_rows = []

            for theme in proxy.columns:
                key = (dt, theme)
                if key not in regime_today.index:
                    continue

                r = regime_today.loc[key]

                if bool(r["entry_eligible"]):
                    base_w = BASE_WEIGHT_BY_THEME.get(theme, 0.0)

                    if base_w > 0:
                        day_rows.append({
                            "theme": theme,
                            "score": r["theme_opportunity_score"],
                            "base_weight": base_w,
                            "profile": PROFILE_BY_THEME.get(theme, "UNKNOWN"),
                            "regime": r["theme_regime"],
                        })

            if day_rows:
                chosen = (
                    pd.DataFrame(day_rows)
                    .sort_values(["score", "base_weight"], ascending=[False, False])
                    .iloc[0]
                )

                current_theme = chosen["theme"]
                current_weight = float(chosen["base_weight"])
                current_profile = chosen["profile"]

                trades.append({
                    "trade_date": dt,
                    "action": "ENTER_THEME",
                    "theme": current_theme,
                    "profile": current_profile,
                    "cycle_weight": current_weight,
                    "score": chosen["score"],
                    "regime": chosen["regime"],
                    "nav": nav,
                })

        # ====================================================
        # Check exit signal for current theme
        # ====================================================
        if current_theme is not None:
            key = (dt, current_theme)

            if key in regime_today.index:
                r = regime_today.loc[key]

                if bool(r["exit_signal"]):
                    trades.append({
                        "trade_date": dt,
                        "action": "EXIT_THEME",
                        "theme": current_theme,
                        "profile": current_profile,
                        "cycle_weight": current_weight,
                        "score": r["theme_opportunity_score"],
                        "regime": r["theme_regime"],
                        "nav": nav,
                    })

                    current_theme = None
                    current_weight = 0.0
                    current_profile = None

        # ====================================================
        # Portfolio Return
        # ====================================================
        cycle_weight = current_weight if current_theme is not None else 0.0
        defensive_weight = 1.0 - cycle_weight
        anchor_weight = defensive_weight * ANCHOR_DEFENSIVE_WEIGHT
        rf_weight = defensive_weight * (1 - ANCHOR_DEFENSIVE_WEIGHT)

        ret = anchor_weight * anchor_ret.loc[dt] + rf_weight * RISK_FREE_DAILY

        if current_theme is not None:
            ret += cycle_weight * proxy.loc[dt, current_theme]

        nav *= 1 + ret

        rows.append({
            "trade_date": dt,
            "portfolio_ret": ret,
            "nav": nav,
            "current_theme": current_theme,
            "profile": current_profile,
            "cycle_weight": cycle_weight,
            "anchor_weight": anchor_weight,
            "risk_free_weight": rf_weight,
        })

    nav_df = pd.DataFrame(rows)
    trades_df = pd.DataFrame(trades)

    summary = pd.DataFrame([{
        "strategy": "SINGLE_THEME_PROFILE_BASE",
        "avg_cycle_weight": nav_df["cycle_weight"].mean(),
        "max_cycle_weight": nav_df["cycle_weight"].max(),
        "avg_anchor_weight": nav_df["anchor_weight"].mean(),
        "avg_risk_free_weight": nav_df["risk_free_weight"].mean(),
        "num_entries": int((trades_df["action"] == "ENTER_THEME").sum()) if not trades_df.empty else 0,
        "num_exits": int((trades_df["action"] == "EXIT_THEME").sum()) if not trades_df.empty else 0,
        **metrics(nav_df["portfolio_ret"]),
    }])

    OUT_SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(OUT_SUMMARY, index=False, encoding="utf-8-sig")
    nav_df.to_csv(OUT_NAV, index=False, encoding="utf-8-sig")
    trades_df.to_csv(OUT_TRADES, index=False, encoding="utf-8-sig")

    print("\n===== SINGLE THEME PROFILE SUMMARY =====")
    print(summary.round(4).to_string(index=False))

    print("\n===== TRADES =====")
    if trades_df.empty:
        print("NO TRADES")
    else:
        print(trades_df.round(4).to_string(index=False))

    print("\n===== HOLDING DAYS =====")
    print(nav_df["current_theme"].value_counts(dropna=False).to_string())

    print("\nsaved:", OUT_SUMMARY)
    print("saved:", OUT_NAV)
    print("saved:", OUT_TRADES)


if __name__ == "__main__":
    main()
