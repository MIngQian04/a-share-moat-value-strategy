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


class QuantQualityEngine:
    """
    Quality 1 v3.

    This layer measures company quality, not cycle direction.

    v3 dimensions:
        1. ROIC persistence
        2. Cash quality
           - cash realization: OCF / Net Income
           - FCF realization: (OCF - CAPEX) / Net Income

    It intentionally does NOT use:
        - valuation
        - Sharpe / Sortino
        - price momentum
        - moat / technology research
    """

    def __init__(
        self,
        store: FinancialPointInTimeStore,
        min_annual_periods: int = 3,
        lookback_years: int = 5,
    ):
        self.store = store
        self.min_annual_periods = min_annual_periods
        self.lookback_years = lookback_years

    def _prepare(self, df: pd.DataFrame, decision_date: str) -> pd.DataFrame:
        if df.empty or "ann_date" not in df.columns or "end_date" not in df.columns:
            return pd.DataFrame()

        out = df.copy()
        out["ann_date"] = out["ann_date"].astype(str)
        out["end_date"] = out["end_date"].astype(str)
        out = out[out["ann_date"] <= decision_date]
        out = out.sort_values(["end_date", "ann_date"])
        out = out.drop_duplicates("end_date", keep="last")

        # Annual reports only: cumulative YTD statement values become comparable.
        out = out[out["end_date"].str.endswith("1231")]

        return out.tail(self.lookback_years)

    @staticmethod
    def _safe_div(num, den):
        if pd.isna(num) or pd.isna(den) or abs(den) < 1e-12:
            return np.nan
        return num / den

    @staticmethod
    def _median(values):
        s = pd.Series(values, dtype=float).replace([np.inf, -np.inf], np.nan).dropna()
        return np.nan if s.empty else float(s.median())

    @staticmethod
    def _positive_ratio(values):
        s = pd.Series(values, dtype=float).replace([np.inf, -np.inf], np.nan).dropna()
        return np.nan if s.empty else float((s > 0).mean())

    @staticmethod
    def _stability(values):
        s = pd.Series(values, dtype=float).replace([np.inf, -np.inf], np.nan).dropna()
        if len(s) < 3:
            return np.nan
        med = s.median()
        mad = (s - med).abs().median()
        scale = max(abs(med), 0.05)
        return float(1.0 / (1.0 + mad / scale))

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

            ebit = first_available(i, ["ebit", "operate_profit", "total_profit"])
            net_income = first_available(i, ["n_income_attr_p", "n_income", "net_profit"])
            ocf = first_available(c, ["n_cashflow_act", "net_cash_flows_oper_act"])
            capex_cash_paid = first_available(
                c, ["c_pay_acq_const_fiolta", "c_pay_acq_const_fa_intan"]
            )

            total_assets = first_available(b, ["total_assets"])
            total_liab = first_available(b, ["total_liab"])
            cash = first_available(
                b, ["money_cap", "cash_reser_cb", "cash_cash_equ_end_period"]
            )
            cur_liab = first_available(b, ["total_cur_liab"])
            noncur_liab = first_available(b, ["total_ncl", "total_non_cur_liab"])

            debt = np.nan
            debt_parts = [x for x in [cur_liab, noncur_liab] if pd.notna(x)]
            if debt_parts:
                debt = sum(debt_parts)
            elif pd.notna(total_liab):
                debt = total_liab

            invested_capital = np.nan
            if pd.notna(total_assets):
                invested_capital = total_assets
                if pd.notna(cash):
                    invested_capital -= cash

            roic_proxy = self._safe_div(ebit, invested_capital)

            cash_conversion = (
                self._safe_div(ocf, net_income)
                if pd.notna(net_income) and net_income > 0
                else np.nan
            )

            free_cash_flow = (
                ocf - capex_cash_paid
                if pd.notna(ocf) and pd.notna(capex_cash_paid)
                else np.nan
            )

            fcf_realization = (
                self._safe_div(free_cash_flow, net_income)
                if pd.notna(net_income) and net_income > 0
                else np.nan
            )

            rows.append({
                "end_date": end_date,
                "ebit": ebit,
                "net_income": net_income,
                "operating_cash_flow": ocf,
                "capex_cash_paid": capex_cash_paid,
                "free_cash_flow": free_cash_flow,
                "total_assets": total_assets,
                "total_liab": total_liab,
                "debt_proxy": debt,
                "invested_capital_proxy": invested_capital,
                "roic_proxy": roic_proxy,
                "cash_conversion": cash_conversion,
                "fcf_realization": fcf_realization,
            })

        return pd.DataFrame(rows)

    def analyze_history(self, hist: pd.DataFrame) -> dict:
        if hist.empty or len(hist) < self.min_annual_periods:
            return {
                "quality_data_status": "INSUFFICIENT_DATA",
                "annual_periods": len(hist),
                "median_roic_proxy": np.nan,
                "roic_positive_ratio": np.nan,
                "roic_stability": np.nan,
                "median_cash_conversion": np.nan,
                "cash_realization_good_ratio": np.nan,
                "median_fcf_realization": np.nan,
                "fcf_positive_ratio": np.nan,
                "roic_persistence_score": np.nan,
                "cash_quality_score": np.nan,
                "quant_quality_score": np.nan,
                "quant_quality_rank": np.nan,
                "quality_evidence": "INSUFFICIENT_DATA",
                "quality_flags": "",
            }

        roic = hist["roic_proxy"]
        cc = hist["cash_conversion"]
        fcf_r = hist["fcf_realization"]

        median_roic = self._median(roic)
        roic_positive_ratio = self._positive_ratio(roic)
        roic_stability = self._stability(roic)

        median_cc = self._median(cc)
        cc_valid = pd.Series(cc, dtype=float).replace([np.inf, -np.inf], np.nan).dropna()
        cash_realization_good_ratio = (
            np.nan if cc_valid.empty else float(((cc_valid >= 0.8) & (cc_valid <= 5.0)).mean())
        )

        median_fcf_realization = self._median(fcf_r)
        fcf_valid = pd.Series(fcf_r, dtype=float).replace([np.inf, -np.inf], np.nan).dropna()
        fcf_positive_ratio = np.nan if fcf_valid.empty else float((fcf_valid > 0).mean())

        roic_level_component = (
            np.nan if pd.isna(median_roic)
            else float(np.clip((median_roic + 0.05) / 0.25, 0, 1))
        )
        roic_components = [roic_level_component, roic_positive_ratio, roic_stability]
        roic_components = [x for x in roic_components if pd.notna(x)]
        roic_score = np.nan if not roic_components else 100.0 * float(np.mean(roic_components))

        # OCF/NI is an evidence ratio, not a "higher is better" ratio.
        # 0.8-1.5 is the healthy zone. Above 1.5 remains healthy but is capped.
        if pd.isna(median_cc):
            cash_realization_level = np.nan
        elif median_cc < 0:
            cash_realization_level = 0.0
        elif median_cc < 0.5:
            cash_realization_level = float(0.4 * median_cc / 0.5)
        elif median_cc < 0.8:
            cash_realization_level = float(0.4 + 0.4 * (median_cc - 0.5) / 0.3)
        elif median_cc <= 1.5:
            cash_realization_level = float(0.8 + 0.2 * (median_cc - 0.8) / 0.7)
        else:
            cash_realization_level = 1.0

        # Detect denominator distortion: very large OCF/NI combined with a weak
        # earnings/capital base. The ratio is then treated as unreliable evidence.
        cash_ratio_distorted = bool(
            pd.notna(median_cc)
            and median_cc >= 5.0
            and (
                (pd.notna(median_roic) and median_roic < 0.03)
                or (pd.notna(roic_positive_ratio) and roic_positive_ratio <= 0.6)
            )
        )

        if cash_ratio_distorted:
            cash_realization_level = min(cash_realization_level, 0.5)
            cash_realization_good_ratio = min(cash_realization_good_ratio, 0.5)

        if pd.isna(median_fcf_realization):
            fcf_level_component = np.nan
        else:
            # FCF realization is also capped. Extreme values can be denominator effects.
            capped_fcf = float(np.clip(median_fcf_realization, -0.5, 1.5))
            fcf_level_component = float((capped_fcf + 0.5) / 2.0)

        cash_components = [
            cash_realization_level,
            cash_realization_good_ratio,
            fcf_level_component,
            fcf_positive_ratio,
        ]
        cash_components = [x for x in cash_components if pd.notna(x)]
        cash_quality_score = (
            np.nan if not cash_components else 100.0 * float(np.mean(cash_components))
        )

        score_components = [x for x in [roic_score, cash_quality_score] if pd.notna(x)]
        quant_quality_score = (
            np.nan if not score_components else float(np.mean(score_components))
        )

        evidence = []
        flags = []

        if pd.notna(roic_score) and roic_score >= 70:
            evidence.append("CAPITAL_EFFICIENT")
        elif pd.notna(roic_score) and roic_score < 50:
            evidence.append("WEAK_CAPITAL_EFFICIENCY")

        if pd.notna(cash_quality_score) and cash_quality_score >= 70:
            evidence.append("CASH_SUPPORTED")
        elif pd.notna(cash_quality_score) and cash_quality_score < 50:
            evidence.append("WEAK_CASH_SUPPORT")

        if cash_ratio_distorted:
            evidence.append("CASH_RATIO_DISTORTED")

        if pd.notna(median_fcf_realization) and median_fcf_realization < 0:
            evidence.append("FCF_CONSUMING")
        elif pd.notna(fcf_positive_ratio) and fcf_positive_ratio >= 0.6:
            evidence.append("FCF_PERSISTENT")

        if pd.notna(median_roic) and median_roic >= 0.12:
            flags.append("HIGH_MEDIAN_ROIC")
        if pd.notna(roic_positive_ratio) and roic_positive_ratio >= 0.8:
            flags.append("PERSISTENT_POSITIVE_ROIC")
        if pd.notna(roic_stability) and roic_stability >= 0.7:
            flags.append("STABLE_ROIC")
        if pd.notna(median_cc) and median_cc >= 0.8:
            flags.append("HEALTHY_CASH_REALIZATION")
        if pd.notna(fcf_positive_ratio) and fcf_positive_ratio >= 0.6:
            flags.append("PERSISTENT_POSITIVE_FCF")

        return {
            "quality_data_status": "OK",
            "annual_periods": len(hist),
            "median_roic_proxy": median_roic,
            "roic_positive_ratio": roic_positive_ratio,
            "roic_stability": roic_stability,
            "median_cash_conversion": median_cc,
            "cash_realization_good_ratio": cash_realization_good_ratio,
            "median_fcf_realization": median_fcf_realization,
            "fcf_positive_ratio": fcf_positive_ratio,
            "roic_persistence_score": roic_score,
            "cash_quality_score": cash_quality_score,
            "quant_quality_score": quant_quality_score,
            "quant_quality_rank": np.nan,
            "quality_evidence": "|".join(evidence),
            "quality_flags": "|".join(flags),
        }

    def analyze_candidates(self, candidates: pd.DataFrame, decision_date: str) -> pd.DataFrame:
        rows = []
        for _, candidate in candidates.iterrows():
            ts_code = str(candidate["ts_code"])
            hist = self.build_history(ts_code, decision_date)
            result = self.analyze_history(hist)
            rows.append({
                "theme": candidate["theme"],
                "ts_code": ts_code,
                "decision_date": decision_date,
                **result,
            })

        out = pd.DataFrame(rows)
        if not out.empty:
            out["quant_quality_rank"] = (
                out.groupby("theme")["quant_quality_score"]
                .rank(method="dense", ascending=False)
            )
        return out
