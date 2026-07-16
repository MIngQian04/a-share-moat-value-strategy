from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd

@dataclass(frozen=True)
class SellSideBrakeResult:
    brake_state: str
    brake_reason: str
    brake_cap: float
    trend_armed: bool
    current_price: float
    ma5: float
    ma20: float
    ma40: float
    ma_spread: float
    amount_ratio_5_20: float
    ret5: float
    distribution_warning: bool

class SellSideBrakeEngine:
    def __init__(self, compression_spread=0.03, compression_cap=0.45,
                 compression_warning_cap=0.35, trend_cap=0.25, full_cap=0.0,
                 top_volume_ratio=1.50, stagnation_abs_ret5=0.03):
        self.compression_spread = compression_spread
        self.compression_cap = compression_cap
        self.compression_warning_cap = compression_warning_cap
        self.trend_cap = trend_cap
        self.full_cap = full_cap
        self.top_volume_ratio = top_volume_ratio
        self.stagnation_abs_ret5 = stagnation_abs_ret5

    @staticmethod
    def apply_cap(original_exposure, brake_cap):
        original = 0.0 if pd.isna(original_exposure) else float(original_exposure)
        cap = 1.0 if pd.isna(brake_cap) else float(brake_cap)
        return max(0.0, min(original, cap))

    def evaluate_until(self, dt, theme, close_df, amount_df, *, trend_armed_prev):
        if theme not in close_df.columns:
            return self._empty("PRICE_SERIES_MISSING", trend_armed_prev)
        close = pd.to_numeric(close_df[theme], errors="coerce").loc[:dt].dropna()
        if close.empty:
            return self._empty("PRICE_HISTORY_EMPTY", trend_armed_prev)

        current = float(close.iloc[-1])
        ma5 = float(close.tail(5).mean()) if len(close) >= 5 else np.nan
        ma20 = float(close.tail(20).mean()) if len(close) >= 20 else np.nan
        ma40 = float(close.tail(40).mean()) if len(close) >= 40 else np.nan
        ret5 = float(current / close.iloc[-6] - 1.0) if len(close) >= 6 else np.nan

        amount_ratio = np.nan
        if theme in amount_df.columns:
            amount = pd.to_numeric(amount_df[theme], errors="coerce").loc[:dt].dropna()
            if len(amount) >= 20:
                a20 = float(amount.tail(20).mean())
                if a20 > 0:
                    amount_ratio = float(amount.tail(5).mean()) / a20

        armed_today = (
            np.isfinite(ma5) and np.isfinite(ma20) and np.isfinite(ma40)
            and ma5 > ma20 > ma40
        )
        armed = bool(trend_armed_prev or armed_today)

        spread = np.nan
        if np.isfinite(ma5) and np.isfinite(ma20) and np.isfinite(ma40):
            lo, hi = min(ma5, ma20, ma40), max(ma5, ma20, ma40)
            if lo > 0:
                spread = hi / lo - 1.0

        warning = (
            np.isfinite(amount_ratio) and np.isfinite(ret5)
            and amount_ratio >= self.top_volume_ratio
            and abs(ret5) <= self.stagnation_abs_ret5
        )

        if not armed:
            return self._r("DISABLED", "TREND_NOT_ARMED", 1.0, armed, current, ma5, ma20, ma40, spread, amount_ratio, ret5, warning)
        if not (np.isfinite(ma20) and np.isfinite(ma40)):
            return self._r("OFF", "INSUFFICIENT_MA_DATA", 1.0, armed, current, ma5, ma20, ma40, spread, amount_ratio, ret5, warning)
        if current < ma40:
            return self._r("FULL_BRAKE", "CLOSE_BELOW_MA40_AFTER_TREND_ARMED", self.full_cap, armed, current, ma5, ma20, ma40, spread, amount_ratio, ret5, warning)
        if current < ma20:
            reason = "CLOSE_BELOW_MA20_AFTER_TREND_ARMED"
            if warning:
                reason += "|TOP_VOLUME_STAGNATION_WARNING"
            return self._r("TREND_BRAKE", reason, self.trend_cap, armed, current, ma5, ma20, ma40, spread, amount_ratio, ret5, warning)
        if np.isfinite(spread) and spread <= self.compression_spread:
            cap = self.compression_warning_cap if warning else self.compression_cap
            reason = f"MA5_MA20_MA40_COMPRESSION<={self.compression_spread:.1%}"
            if warning:
                reason += "|TOP_VOLUME_STAGNATION_WARNING"
            return self._r("COMPRESSION_BRAKE", reason, cap, armed, current, ma5, ma20, ma40, spread, amount_ratio, ret5, warning)
        reason = "TOP_VOLUME_STAGNATION_WARNING_ONLY" if warning else "NO_BRAKE"
        return self._r("OFF", reason, 1.0, armed, current, ma5, ma20, ma40, spread, amount_ratio, ret5, warning)

    @staticmethod
    def _r(state, reason, cap, armed, current, ma5, ma20, ma40, spread, amount_ratio, ret5, warning):
        return SellSideBrakeResult(state, reason, cap, armed, current, ma5, ma20, ma40, spread, amount_ratio, ret5, warning)

    @staticmethod
    def _empty(reason, armed):
        return SellSideBrakeResult("DISABLED", reason, 1.0, bool(armed), np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, False)
