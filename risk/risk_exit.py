from __future__ import annotations

import numpy as np
import pandas as pd


class RiskExitEngine:
    """Daily price-risk overlay.

    Cycle/fundamental state explains why an asset may be held.
    This engine independently decides whether price damage requires
    HOLD, REDUCE, or EXIT. EXIT has the highest decision priority.
    """

    def __init__(
        self,
        peak_lookback: int = 120,
        hard_drawdown: float = -0.25,
        soft_drawdown: float = -0.15,
        trend_ma: int = 60,
        momentum_window: int = 20,
        hard_trend_momentum: float = -0.10,
        min_history: int = 60,
    ):
        self.peak_lookback = peak_lookback
        self.hard_drawdown = hard_drawdown
        self.soft_drawdown = soft_drawdown
        self.trend_ma = trend_ma
        self.momentum_window = momentum_window
        self.hard_trend_momentum = hard_trend_momentum
        self.min_history = min_history

    def evaluate_series(self, prices: pd.Series) -> dict:
        s = pd.to_numeric(prices, errors="coerce").dropna().sort_index()

        if len(s) < self.min_history:
            return {
                "risk_exit_status": "UNKNOWN",
                "risk_exit_reason": "INSUFFICIENT_PRICE_HISTORY",
                "current_price": np.nan if s.empty else float(s.iloc[-1]),
                "peak_price": np.nan,
                "drawdown_from_peak": np.nan,
                "ma60": np.nan,
                "ret_20d": np.nan,
            }

        current = float(s.iloc[-1])
        recent = s.iloc[-self.peak_lookback:]
        peak = float(recent.max())
        drawdown = current / peak - 1.0 if peak > 0 else np.nan

        ma = float(s.iloc[-self.trend_ma:].mean())
        ret20 = (
            current / float(s.iloc[-self.momentum_window - 1]) - 1.0
            if len(s) > self.momentum_window
            else np.nan
        )

        reasons = []

        if pd.notna(drawdown) and drawdown <= self.hard_drawdown:
            reasons.append(f"PEAK_DRAWDOWN<={self.hard_drawdown:.0%}")
            status = "EXIT"
        elif current < ma and pd.notna(ret20) and ret20 <= self.hard_trend_momentum:
            reasons.extend(["BELOW_MA60", f"RET20<={self.hard_trend_momentum:.0%}"])
            status = "EXIT"
        elif pd.notna(drawdown) and drawdown <= self.soft_drawdown:
            reasons.append(f"PEAK_DRAWDOWN<={self.soft_drawdown:.0%}")
            status = "REDUCE"
        elif current < ma and pd.notna(ret20) and ret20 < 0:
            reasons.extend(["BELOW_MA60", "RET20_NEGATIVE"])
            status = "REDUCE"
        else:
            reasons.append("NO_EXIT_TRIGGER")
            status = "HOLD"

        return {
            "risk_exit_status": status,
            "risk_exit_reason": "|".join(reasons),
            "current_price": current,
            "peak_price": peak,
            "drawdown_from_peak": drawdown,
            "ma60": ma,
            "ret_20d": ret20,
        }

    def evaluate_candidates(self, candidates: pd.DataFrame, close: pd.DataFrame) -> pd.DataFrame:
        if "theme" not in candidates.columns or "ts_code" not in candidates.columns:
            raise ValueError("candidates must contain columns: theme, ts_code")

        rows = []
        for _, row in candidates[["theme", "ts_code"]].drop_duplicates().iterrows():
            code = row["ts_code"]
            result = (
                self.evaluate_series(close[code])
                if code in close.columns
                else {
                    "risk_exit_status": "UNKNOWN",
                    "risk_exit_reason": "PRICE_SERIES_MISSING",
                    "current_price": np.nan,
                    "peak_price": np.nan,
                    "drawdown_from_peak": np.nan,
                    "ma60": np.nan,
                    "ret_20d": np.nan,
                }
            )
            rows.append({"theme": row["theme"], "ts_code": code, **result})

        return pd.DataFrame(rows)


def apply_position_action(df: pd.DataFrame) -> pd.DataFrame:
    """Add position_action with risk exit priority.

    EXIT/REDUCE from risk_exit_status overrides cycle/fundamental labels.
    Otherwise, the existing final_bucket/fundamental_direction is preserved
    as a research label rather than a hard trading instruction.
    """
    out = df.copy()

    def decide(row):
        risk = row.get("risk_exit_status")
        if risk == "EXIT":
            return "EXIT"
        if risk == "REDUCE":
            return "REDUCE"
        if risk == "UNKNOWN":
            return "WATCH"

        final_bucket = row.get("final_bucket", "")
        direction = row.get("fundamental_direction", "")

        if final_bucket == "FINAL_CANDIDATE" and direction in {"RECOVERING", "BOTTOMING"}:
            return "ACCUMULATE_OR_HOLD"
        if final_bucket == "FINAL_CANDIDATE" and direction == "HARVESTING":
            return "HOLD"
        if direction == "DETERIORATING":
            return "WATCH"
        return "WATCH"

    out["position_action"] = out.apply(decide, axis=1)
    return out
