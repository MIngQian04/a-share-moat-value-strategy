from __future__ import annotations

import numpy as np
import pandas as pd


SCORE_COLUMNS = [
    "demand_certainty",
    "bottleneck_strength",
    "value_capture",
    "exposure_confidence",
    "competition_risk",
    "substitution_risk",
]


def score_future_thesis(frame: pd.DataFrame) -> pd.DataFrame:
    """Score a forward-looking thesis without rewarding current accounting profit.

    All inputs use a 1-5 research scale. Demand, bottlenecks, value capture and
    listed-company exposure are positive; competition and substitution are
    explicit penalties. The result is a hypothesis ranking, not a forecast.
    """
    out = frame.copy()
    missing = set(SCORE_COLUMNS) - set(out.columns)
    if missing:
        raise ValueError(f"missing future-thesis columns: {sorted(missing)}")
    for col in SCORE_COLUMNS:
        out[col] = pd.to_numeric(out[col], errors="raise")
        if not out[col].between(1, 5).all():
            raise ValueError(f"{col} must be between 1 and 5")
    positive = (
        0.30 * out["demand_certainty"]
        + 0.25 * out["bottleneck_strength"]
        + 0.25 * out["value_capture"]
        + 0.20 * out["exposure_confidence"]
    )
    penalty = 0.12 * (out["competition_risk"] - 1) + 0.08 * (out["substitution_risk"] - 1)
    out["future_thesis_score"] = ((positive - 1 - penalty) / 4 * 100).clip(0, 100)
    return out


def valuation_gate(frame: pd.DataFrame) -> pd.Series:
    """Classify valuation as a constraint, deliberately not a thesis input."""
    pe = pd.to_numeric(frame.get("pe_ttm"), errors="coerce")
    pb = pd.to_numeric(frame.get("pb"), errors="coerce")
    ps = pd.to_numeric(frame.get("ps_ttm"), errors="coerce")
    expensive = pe.gt(60) | pb.gt(8) | ps.gt(10)
    loss_or_unproven = pe.isna() | pe.le(0)
    reasonable = pe.between(0, 35) & pb.le(6) & ps.le(8)
    return pd.Series(
        np.select(
            [loss_or_unproven & expensive, expensive, loss_or_unproven, reasonable],
            ["UNPROVEN_AND_EXPENSIVE", "EXPENSIVE", "UNPROVEN", "REASONABLE"],
            default="FAIR_TO_RICH",
        ),
        index=frame.index,
    )


def research_tier(frame: pd.DataFrame) -> pd.Series:
    """Turn thesis and valuation checks into research priorities, never buy calls."""
    score = pd.to_numeric(frame["future_thesis_score"], errors="coerce")
    gate = frame["valuation_gate"].astype(str)
    severe = gate.isin({"EXPENSIVE", "UNPROVEN_AND_EXPENSIVE"})
    return pd.Series(
        np.select(
            [score.ge(72) & ~severe, score.ge(62), score.ge(50)],
            ["CORE_RESEARCH", "OPTIONALITY_WATCH", "SECONDARY_WATCH"],
            default="PASS_FOR_NOW",
        ),
        index=frame.index,
    )


def decision_status(frame: pd.DataFrame) -> pd.Series:
    """Apply cash-earnings, conservative value and timing checks after thesis ranking."""
    core = frame["research_tier"].eq("CORE_RESEARCH")
    cash_pass = frame["financial_check"].eq("PASS_SURVIVAL")
    margin = pd.to_numeric(frame["dcf_margin_of_safety"], errors="coerce")
    value_supported = margin.ge(0) & frame["valuation_gate"].isin({"REASONABLE", "FAIR_TO_RICH"})
    timing = frame["timing_status"].eq("BOTTOM_VOLUME_CONFIRMATION")
    return pd.Series(
        np.select(
            [core & cash_pass & value_supported & timing,
             core & cash_pass & value_supported,
             core & cash_pass,
             core & ~cash_pass],
            ["MANUAL_ENTRY_REVIEW", "VALUE_VERIFIED_WAIT_TIMING",
             "THESIS_STRONG_PRICE_UNSUPPORTED", "FAIL_CASH_CHECK"],
            default="THEME_WATCH_ONLY",
        ),
        index=frame.index,
    )
