from __future__ import annotations

import numpy as np
import pandas as pd

from fundamental.point_in_time import FinancialPointInTimeStore


def first_available(row, names):
    if row is None:
        return np.nan
    for name in names:
        if name in row.index and pd.notna(row[name]):
            return row[name]
    return np.nan


class FundamentalDirectionEngine:
    """
    Fundamental Direction v2.

    This model detects financial direction, not financial quality.

    Key changes from v1:
        - Revenue still uses YoY growth.
        - EBIT no longer uses raw YoY percentage growth.
          It uses EBIT margin trajectory.
        - Operating cash flow no longer uses raw YoY percentage growth.
          It uses OCF margin trajectory.
        - HARVESTING requires sustained strong margin level
          plus weakening acceleration.

    States:
        DETERIORATING
        BOTTOMING
        RECOVERING
        HARVESTING
        INSUFFICIENT_DATA
    """

    def __init__(
        self,
        store: FinancialPointInTimeStore,
        min_periods: int = 6,
        recent_window: int = 6,
        harvest_window: int = 4,
        strong_margin_threshold: float = 0.12,
        strong_ocf_margin_threshold: float = 0.08,
    ):
        self.store = store
        self.min_periods = min_periods
        self.recent_window = recent_window
        self.harvest_window = harvest_window
        self.strong_margin_threshold = strong_margin_threshold
        self.strong_ocf_margin_threshold = strong_ocf_margin_threshold

    @staticmethod
    def _prepare(df: pd.DataFrame, decision_date: str) -> pd.DataFrame:
        if df.empty or "ann_date" not in df.columns or "end_date" not in df.columns:
            return pd.DataFrame()

        out = df.copy()
        out["ann_date"] = out["ann_date"].astype(str)
        out["end_date"] = out["end_date"].astype(str)
        out = out[out["ann_date"] <= decision_date]
        out = out.sort_values(["end_date", "ann_date"])
        out = out.drop_duplicates("end_date", keep="last")
        return out

    @staticmethod
    def _quarter(end_date: str) -> str:
        return str(end_date)[4:]

    @staticmethod
    def _safe_growth(current, previous):
        if pd.isna(current) or pd.isna(previous) or abs(previous) < 1e-12:
            return np.nan
        return current / previous - 1.0

    @staticmethod
    def _safe_div(num, den):
        if pd.isna(num) or pd.isna(den) or abs(den) < 1e-12:
            return np.nan
        return num / den

    @staticmethod
    def _slope(values):
        s = pd.Series(values, dtype=float).replace([np.inf, -np.inf], np.nan).dropna()
        if len(s) < 3:
            return np.nan
        x = np.arange(len(s), dtype=float)
        return float(np.polyfit(x, s.values, 1)[0])

    @staticmethod
    def _acceleration(values):
        s = pd.Series(values, dtype=float).replace([np.inf, -np.inf], np.nan).dropna()
        if len(s) < 4:
            return np.nan
        first_diff = s.diff().dropna()
        if len(first_diff) < 3:
            return np.nan
        x = np.arange(len(first_diff), dtype=float)
        return float(np.polyfit(x, first_diff.values, 1)[0])

    def build_history(self, ts_code: str, decision_date: str) -> pd.DataFrame:
        inc = self._prepare(self.store.read_endpoint("income", ts_code), decision_date)
        cf = self._prepare(self.store.read_endpoint("cashflow", ts_code), decision_date)
        bs = self._prepare(self.store.read_endpoint("balancesheet", ts_code), decision_date)

        end_dates = sorted(
            set(inc.get("end_date", pd.Series(dtype=str)).tolist())
            | set(cf.get("end_date", pd.Series(dtype=str)).tolist())
            | set(bs.get("end_date", pd.Series(dtype=str)).tolist())
        )

        rows = []
        for end_date in end_dates:
            i = inc[inc["end_date"] == end_date]
            c = cf[cf["end_date"] == end_date]
            b = bs[bs["end_date"] == end_date]

            i = None if i.empty else i.iloc[-1]
            c = None if c.empty else c.iloc[-1]
            b = None if b.empty else b.iloc[-1]

            revenue = first_available(i, ["revenue", "total_revenue"])
            ebit = first_available(i, ["ebit", "operate_profit", "total_profit"])
            ocf = first_available(c, ["n_cashflow_act", "net_cash_flows_oper_act"])

            rows.append({
                "end_date": end_date,
                "revenue": revenue,
                "ebit": ebit,
                "operating_cash_flow": ocf,
                "ebit_margin": self._safe_div(ebit, revenue),
                "ocf_margin": self._safe_div(ocf, revenue),
                "capex_cash_paid": first_available(
                    c, ["c_pay_acq_const_fiolta", "c_pay_acq_const_fa_intan"]
                ),
                "total_debt": first_available(b, ["total_liab", "total_cur_liab"]),
            })

        hist = pd.DataFrame(rows)
        if hist.empty:
            return hist

        hist["year"] = hist["end_date"].str[:4].astype(int)
        hist["quarter_key"] = hist["end_date"].map(self._quarter)

        # Revenue is usually non-negative and meaningful as YoY.
        revenue_yoy = []
        for _, row in hist.iterrows():
            prev = hist[
                (hist["year"] == row["year"] - 1)
                & (hist["quarter_key"] == row["quarter_key"])
            ]
            prev_value = np.nan if prev.empty else prev.iloc[-1]["revenue"]
            revenue_yoy.append(self._safe_growth(row["revenue"], prev_value))

        hist["revenue_yoy"] = revenue_yoy

        return hist

    def classify(self, hist: pd.DataFrame) -> dict:
        if hist.empty or len(hist) < self.min_periods:
            return {
                "fundamental_direction": "INSUFFICIENT_DATA",
                "direction_score": np.nan,
                "revenue_yoy": np.nan,
                "ebit_margin": np.nan,
                "ocf_margin": np.nan,
                "revenue_yoy_slope": np.nan,
                "ebit_margin_slope": np.nan,
                "ocf_margin_slope": np.nan,
                "ebit_margin_acceleration": np.nan,
                "ocf_margin_acceleration": np.nan,
                "direction_flags": "",
            }

        recent = hist.tail(self.recent_window).copy()
        harvest_recent = hist.tail(self.harvest_window).copy()
        latest = recent.iloc[-1]

        revenue_slope = self._slope(recent["revenue_yoy"])
        ebit_margin_slope = self._slope(recent["ebit_margin"])
        ocf_margin_slope = self._slope(recent["ocf_margin"])

        ebit_margin_acc = self._acceleration(recent["ebit_margin"])
        ocf_margin_acc = self._acceleration(recent["ocf_margin"])

        revenue_yoy = latest.get("revenue_yoy")
        ebit_margin = latest.get("ebit_margin")
        ocf_margin = latest.get("ocf_margin")

        positive_slopes = sum(
            pd.notna(x) and x > 0
            for x in [revenue_slope, ebit_margin_slope, ocf_margin_slope]
        )
        negative_slopes = sum(
            pd.notna(x) and x < 0
            for x in [revenue_slope, ebit_margin_slope, ocf_margin_slope]
        )

        positive_levels = sum(
            pd.notna(x) and x > 0
            for x in [revenue_yoy, ebit_margin, ocf_margin]
        )
        weak_levels = sum(
            pd.notna(x) and x < 0
            for x in [revenue_yoy, ebit_margin, ocf_margin]
        )

        strong_margin_periods = (
            (harvest_recent["ebit_margin"] >= self.strong_margin_threshold)
            | (harvest_recent["ocf_margin"] >= self.strong_ocf_margin_threshold)
        ).sum()

        decelerating_margin = (
            (pd.notna(ebit_margin_acc) and ebit_margin_acc < 0)
            or (pd.notna(ocf_margin_acc) and ocf_margin_acc < 0)
        )

        sustained_strong = strong_margin_periods >= max(3, self.harvest_window - 1)

        flags = []
        score = 0.0

        score += positive_slopes
        score -= negative_slopes
        score += 0.5 * positive_levels
        score -= 0.5 * weak_levels

        # HARVESTING should not trigger from one good quarter.
        # It requires sustained strong margins and weakening acceleration.
        if sustained_strong and decelerating_margin and positive_levels >= 2:
            state = "HARVESTING"
            flags.append("SUSTAINED_STRONG_MARGIN_DECELERATING")

        elif positive_slopes >= 2 and positive_levels >= 2:
            state = "RECOVERING"
            flags.append("MULTI_METRIC_RECOVERY")

        elif positive_slopes >= 2 and weak_levels >= 2:
            state = "BOTTOMING"
            flags.append("TRAJECTORY_IMPROVING_FROM_WEAK_BASE")

        elif negative_slopes >= 2 and weak_levels >= 1:
            state = "DETERIORATING"
            flags.append("MARGIN_OR_REVENUE_DETERIORATION")

        elif positive_slopes > negative_slopes:
            state = "BOTTOMING"
            flags.append("EARLY_IMPROVEMENT")

        elif negative_slopes > positive_slopes:
            state = "DETERIORATING"
            flags.append("WEAKENING_TRAJECTORY")

        else:
            state = "BOTTOMING"
            flags.append("MIXED_STABILIZATION")

        return {
            "fundamental_direction": state,
            "direction_score": score,
            "revenue_yoy": revenue_yoy,
            "ebit_margin": ebit_margin,
            "ocf_margin": ocf_margin,
            "revenue_yoy_slope": revenue_slope,
            "ebit_margin_slope": ebit_margin_slope,
            "ocf_margin_slope": ocf_margin_slope,
            "ebit_margin_acceleration": ebit_margin_acc,
            "ocf_margin_acceleration": ocf_margin_acc,
            "strong_margin_periods": int(strong_margin_periods),
            "direction_flags": "|".join(flags),
        }

    def analyze_candidates(self, candidates: pd.DataFrame, decision_date: str) -> pd.DataFrame:
        rows = []

        for _, candidate in candidates.iterrows():
            ts_code = str(candidate["ts_code"])
            hist = self.build_history(ts_code, decision_date)
            result = self.classify(hist)

            rows.append({
                "theme": candidate["theme"],
                "ts_code": ts_code,
                "decision_date": decision_date,
                "n_financial_periods": len(hist),
                **result,
            })

        return pd.DataFrame(rows)
