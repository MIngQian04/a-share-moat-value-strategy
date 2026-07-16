from __future__ import annotations

import numpy as np
import pandas as pd


INVESTABLE_STATES = {"BOTTOMING", "RECOVERY", "EXPANSION"}


def build_industry_nav(close: pd.DataFrame, membership: pd.DataFrame) -> pd.DataFrame:
    """Build equal-weight SW L1 industry NAVs from current constituents.

    Constituents are equal weighted to prevent a handful of mega-caps from
    masking industry breadth. Membership must contain ``ts_code`` and
    ``l1_name``. This is a market-implied cycle proxy, not a supply-demand model.
    """
    required = {"ts_code", "l1_name"}
    if not required.issubset(membership.columns):
        raise ValueError(f"membership must contain {sorted(required)}")
    prices = close.apply(pd.to_numeric, errors="coerce").sort_index()
    returns = prices.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan)
    out = {}
    active = membership.drop_duplicates("ts_code")
    for industry, group in active.groupby("l1_name"):
        codes = [c for c in group["ts_code"] if c in returns.columns]
        if len(codes) < 3:
            continue
        industry_ret = returns[codes].median(axis=1, skipna=True)
        out[industry] = (1.0 + industry_ret.fillna(0.0)).cumprod()
    return pd.DataFrame(out, index=prices.index)


def classify_industry_cycle(nav: pd.Series, constituent_close: pd.DataFrame | None = None) -> dict:
    s = pd.to_numeric(nav, errors="coerce").dropna()
    if len(s) < 120:
        return {"cycle_state": "INSUFFICIENT_DATA", "cycle_score": np.nan}
    current = float(s.iloc[-1])
    ma20 = float(s.iloc[-20:].mean())
    ma60 = float(s.iloc[-60:].mean())
    ma120 = float(s.iloc[-120:].mean())
    window = s.iloc[-min(252, len(s)):]
    low, high = float(window.min()), float(window.max())
    position = (current - low) / (high - low) if high > low else 0.5
    ret20 = current / float(s.iloc[-21]) - 1 if len(s) > 20 else np.nan
    ret60 = current / float(s.iloc[-61]) - 1 if len(s) > 60 else np.nan
    drawdown = current / high - 1 if high > 0 else np.nan

    breadth = np.nan
    if constituent_close is not None and not constituent_close.empty:
        px = constituent_close.apply(pd.to_numeric, errors="coerce")
        breadth = float((px.iloc[-1] > px.rolling(60, min_periods=40).mean().iloc[-1]).mean())

    if position <= 0.25 and current < ma60 and ret20 <= 0:
        state, score = "DEEP_BOTTOM", 35.0
    elif position <= 0.45 and ret20 > 0 and current >= ma20:
        state, score = "BOTTOMING", 70.0
    elif current > ma60 and ma20 > ma60 and ret60 > 0 and position < 0.80:
        state, score = "RECOVERY", 85.0
    elif current > ma120 and ma20 > ma60 > ma120 and (pd.isna(breadth) or breadth >= 0.55):
        state, score = "EXPANSION", 80.0
    elif position >= 0.80 and ret20 < ret60 / 3:
        state, score = "LATE_CYCLE", 40.0
    elif current < ma60 and ret60 < 0:
        state, score = "CONTRACTION", 20.0
    else:
        state, score = "NEUTRAL", 50.0

    return {
        "cycle_state": state,
        "cycle_score": score,
        "price_position_252": position,
        "return_20d": ret20,
        "return_60d": ret60,
        "drawdown_252": drawdown,
        "above_ma60_breadth": breadth,
        "ma20_over_ma60": ma20 / ma60 - 1 if ma60 else np.nan,
        "ma60_over_ma120": ma60 / ma120 - 1 if ma120 else np.nan,
    }


def industry_cycle_table(close: pd.DataFrame, membership: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    nav = build_industry_nav(close, membership)
    rows = []
    for industry in nav.columns:
        codes = membership.loc[membership["l1_name"].eq(industry), "ts_code"]
        codes = [c for c in codes if c in close.columns]
        result = classify_industry_cycle(nav[industry], close[codes])
        rows.append({"l1_name": industry, "constituents": len(codes), **result})
    table = pd.DataFrame(rows).sort_values(["cycle_score", "l1_name"], ascending=[False, True])
    return table, nav
