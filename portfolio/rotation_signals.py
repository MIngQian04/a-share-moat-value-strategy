"""Transparent, point-in-time price/volume signals for cycle rotation.

This module deliberately separates a *tradable signal* from an investment
recommendation.  A cycle candidate may only receive a base allocation after a
low-position volume confirmation; it may receive additional allocation only
after trend confirmation.  Defensive names must be explicitly approved in the
watchlist, because a dividend yield alone is not evidence of a durable moat.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _last(series: pd.Series, n: int) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna()
    return float(values.iloc[-n]) if len(values) >= n else np.nan


def price_volume_features(close: pd.Series, volume: pd.Series) -> dict:
    """Return only information available at the final observation."""
    price = pd.to_numeric(close, errors="coerce").dropna()
    vol = pd.to_numeric(volume, errors="coerce").reindex(price.index).dropna()
    price = price.reindex(vol.index).dropna()
    if len(price) < 252 or len(vol) < 60:
        return {"signal_state": "INSUFFICIENT_HISTORY"}

    current = float(price.iloc[-1])
    ma20 = float(price.iloc[-20:].mean())
    ma60 = float(price.iloc[-60:].mean())
    low252 = float(price.iloc[-252:].min())
    high252 = float(price.iloc[-252:].max())
    position252 = (current - low252) / (high252 - low252) if high252 > low252 else 0.5
    volume_ratio = float(vol.iloc[-5:].mean() / vol.iloc[-60:].mean()) if vol.iloc[-60:].mean() > 0 else np.nan
    ret20 = current / _last(price, 21) - 1.0
    breakout20 = current >= float(price.iloc[-21:-1].max())

    # "Bottom" means a depressed 252-day price position, not merely a falling price.
    bottom_volume = bool(position252 <= 0.45 and volume_ratio >= 1.20 and current >= ma20)
    trend_confirmed = bool(
        bottom_volume
        and current > ma60
        and ma20 > ma60
        and breakout20
        and volume_ratio >= 1.50
        and ret20 >= 0.08
    )
    return {
        "signal_state": "TREND_ADD" if trend_confirmed else "BOTTOM_BASE" if bottom_volume else "WATCH",
        "close": current,
        "ma20": ma20,
        "ma60": ma60,
        "low252": low252,
        "high252": high252,
        "position252": position252,
        "volume_ratio_5_60": volume_ratio,
        "return_20d": ret20,
        "breakout_20d": breakout20,
        "bottom_volume": bottom_volume,
        "trend_confirmed": trend_confirmed,
    }


def cycle_signal_table(
    candidates: pd.DataFrame, close: pd.DataFrame, volume: pd.DataFrame
) -> pd.DataFrame:
    """Score each pre-screened cycle candidate without forward-looking data."""
    rows = []
    for _, candidate in candidates.drop_duplicates("ts_code").iterrows():
        code = candidate["ts_code"]
        feature = price_volume_features(close[code], volume[code]) if code in close and code in volume else {"signal_state": "PRICE_OR_VOLUME_MISSING"}
        row = {"ts_code": code, "theme": candidate.get("theme"), **feature}
        row["cycle_reaction_score"] = pd.to_numeric(candidate.get("cycle_reaction_score_final"), errors="coerce")
        row["survival_status"] = candidate.get("survival_status")
        row["hard_gate_pass"] = bool(candidate.get("hard_gate_pass", False))
        # A price pattern cannot override survival evidence.  Candidates marked
        # WATCH remain visible in the report but are never allocated.
        if row["signal_state"] in {"BOTTOM_BASE", "TREND_ADD"} and row["hard_gate_pass"] and row["survival_status"] == "SAFE":
            # A simple ranking score; eligibility itself is rule-based above.
            row["priority_score"] = row["cycle_reaction_score"] + 20 * float(row.get("volume_ratio_5_60", 0)) + 30 * float(row.get("trend_confirmed", False))
        else:
            if row["signal_state"] in {"BOTTOM_BASE", "TREND_ADD"} and row["survival_status"] != "SAFE":
                row["signal_state"] = "WATCH_SURVIVAL"
            row["priority_score"] = np.nan
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["priority_score", "ts_code"], ascending=[False, True], na_position="last")


def defensive_signal_table(daily_basic: pd.DataFrame, approved: pd.DataFrame) -> pd.DataFrame:
    """Return only approved moat names that pass dividend and valuation checks."""
    if approved.empty:
        return pd.DataFrame(columns=["ts_code", "name", "defensive_status", "reason"])
    required = {"ts_code", "moat_approved"}
    missing = required - set(approved.columns)
    if missing:
        raise ValueError(f"defensive watchlist is missing columns: {sorted(missing)}")
    fields = [c for c in ["ts_code", "close", "dv_ratio", "pb", "total_mv"] if c in daily_basic]
    out = approved.merge(daily_basic[fields], on="ts_code", how="left")
    out["moat_approved"] = out["moat_approved"].astype(str).str.upper().eq("TRUE")
    out["dv_ratio"] = pd.to_numeric(out.get("dv_ratio"), errors="coerce")
    out["pb"] = pd.to_numeric(out.get("pb"), errors="coerce")
    out["defensive_status"] = np.where(
        out["moat_approved"] & out["dv_ratio"].ge(3.0) & out["pb"].gt(0) & out["pb"].le(3.0),
        "DEFENSIVE_ELIGIBLE", "WATCH",
    )
    out["reason"] = np.where(out["defensive_status"].eq("DEFENSIVE_ELIGIBLE"), "manual moat approval + dividend yield >= 3% + 0 < PB <= 3", "requires current data and/or manual moat approval")
    return out.sort_values(["defensive_status", "dv_ratio"], ascending=[True, False])


def target_weights(cycle: pd.DataFrame, defensive: pd.DataFrame, max_cycle_weight: float = 0.45) -> pd.DataFrame:
    """Convert states into capped target weights; cash remains when no defensive name qualifies."""
    cycle = cycle[cycle["signal_state"].isin(["BOTTOM_BASE", "TREND_ADD"])].copy()
    # Keep the strongest security per industry theme, so an apparently broad
    # portfolio cannot become an accidental single-industry bet.
    if "priority_score" not in cycle.columns:
        cycle["priority_score"] = 0.0
    if "theme" not in cycle.columns:
        cycle["theme"] = cycle["ts_code"]
    cycle = cycle.sort_values("priority_score", ascending=False).groupby("theme", as_index=False).head(1)
    n_add = int(cycle["signal_state"].eq("TREND_ADD").sum())
    target_cycle = min(max_cycle_weight, 0.15 + 0.10 * n_add) if not cycle.empty else 0.0
    cycle["target_weight"] = target_cycle / len(cycle) if len(cycle) else 0.0
    cycle["allocation_bucket"] = "cycle"
    defensive = defensive[defensive["defensive_status"].eq("DEFENSIVE_ELIGIBLE")].copy()
    defensive_budget = 1.0 - target_cycle
    defensive["target_weight"] = defensive_budget / len(defensive) if len(defensive) else 0.0
    defensive["allocation_bucket"] = "defensive"
    cash_weight = defensive_budget if defensive.empty else 0.0
    result = pd.concat([cycle, defensive], ignore_index=True, sort=False)
    result.attrs["cash_weight"] = cash_weight
    result.attrs["cycle_weight"] = target_cycle
    return result
