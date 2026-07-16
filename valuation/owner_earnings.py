from __future__ import annotations

import numpy as np
import pandas as pd


def safe_num(value) -> float:
    try:
        value = float(value)
        return value if np.isfinite(value) else np.nan
    except (TypeError, ValueError):
        return np.nan


def conservative_dcf(
    normalized_owner_earnings: float,
    net_cash: float,
    shares: float,
    growth: float = 0.03,
    discount_rate: float = 0.10,
    terminal_growth: float = 0.025,
    years: int = 5,
) -> float:
    """Estimate equity value per share from normalized owner earnings.

    Growth is deliberately capped because extrapolating a cyclical peak is one
    of the most common DCF errors. Financial companies should use a dedicated
    residual-income model instead of this industrial-company DCF.
    """
    oe, cash, shares = map(safe_num, [normalized_owner_earnings, net_cash, shares])
    if pd.isna(oe) or oe <= 0 or pd.isna(shares) or shares <= 0:
        return np.nan
    g = float(np.clip(growth, -0.02, 0.06))
    r = max(float(discount_rate), terminal_growth + 0.02)
    cash = 0.0 if pd.isna(cash) else cash
    pv, earning = 0.0, oe
    for year in range(1, years + 1):
        earning *= 1.0 + g
        pv += earning / ((1.0 + r) ** year)
    terminal = earning * (1.0 + terminal_growth) / (r - terminal_growth)
    equity_value = pv + terminal / ((1.0 + r) ** years) + cash
    return max(equity_value / shares, 0.0)


def owner_earnings_from_statements(
    income: pd.DataFrame, cashflow: pd.DataFrame, balance: pd.DataFrame, total_shares: float
) -> dict:
    """Calculate normalized owner earnings from annual point-in-time statements."""
    def annual(df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty or "end_date" not in df:
            return pd.DataFrame()
        x = df.copy()
        x["end_date"] = x["end_date"].astype(str)
        if "ann_date" in x:
            x = x.sort_values(["end_date", "ann_date"]).drop_duplicates("end_date", keep="last")
        return x[x["end_date"].str.endswith("1231")].tail(5)

    inc, cf, bs = annual(income), annual(cashflow), annual(balance)
    periods = sorted(set(inc.get("end_date", [])) & set(cf.get("end_date", [])))
    values = []
    for period in periods:
        i = inc[inc["end_date"].eq(period)].iloc[-1]
        c = cf[cf["end_date"].eq(period)].iloc[-1]
        b = bs[bs["end_date"].eq(period)].iloc[-1] if not bs.empty and bs["end_date"].eq(period).any() else pd.Series(dtype=float)
        profit = safe_num(i.get("n_income_attr_p", i.get("n_income")))
        revenue = safe_num(i.get("revenue", i.get("total_revenue")))
        if pd.isna(revenue):
            revenue = safe_num(i.get("total_revenue"))
        operating_cost = safe_num(i.get("oper_cost"))
        gross_margin = (
            (revenue - operating_cost) / revenue
            if pd.notna(revenue) and revenue > 0 and pd.notna(operating_cost)
            else np.nan
        )
        ocf = safe_num(c.get("n_cashflow_act"))
        capex = safe_num(c.get("c_pay_acq_const_fiolta"))
        depreciation = sum(v for v in [safe_num(c.get("depr_fa_coga_dpba")), safe_num(c.get("amort_intang_assets")), safe_num(c.get("lt_amort_deferred_exp"))] if pd.notna(v))
        maintenance_capex = min(capex, depreciation * 1.10) if pd.notna(capex) and depreciation > 0 else capex
        owner = profit + depreciation - maintenance_capex if pd.notna(profit) and pd.notna(maintenance_capex) else np.nan
        equity = safe_num(b.get("total_hldr_eqy_exc_min_int", b.get("total_hldr_eqy_inc_min_int")))
        roe = profit / equity if pd.notna(profit) and pd.notna(equity) and equity > 0 else np.nan
        values.append({"end_date": period, "revenue": revenue, "gross_margin": gross_margin,
                       "owner_earnings": owner,
                       "free_cash_flow": ocf - capex if pd.notna(ocf) and pd.notna(capex) else np.nan,
                       "roe": roe})
    history = pd.DataFrame(values)
    normalized = float(history["owner_earnings"].tail(3).median()) if not history.empty else np.nan
    owner_positive_years = int(history["owner_earnings"].gt(0).sum()) if not history.empty else 0
    fcf_positive_years = int(history["free_cash_flow"].gt(0).sum()) if not history.empty else 0
    owner_mean = float(history["owner_earnings"].mean()) if not history.empty else np.nan
    owner_cv = (
        float(history["owner_earnings"].std(ddof=0) / abs(owner_mean))
        if pd.notna(owner_mean) and owner_mean != 0 else np.nan
    )
    normalized_roe = float(history["roe"].tail(3).median()) if not history.empty else np.nan
    revenue_history = history.dropna(subset=["revenue"])
    if len(revenue_history) >= 2 and revenue_history.iloc[0]["revenue"] > 0 and revenue_history.iloc[-1]["revenue"] > 0:
        first_year = int(str(revenue_history.iloc[0]["end_date"])[:4])
        last_year = int(str(revenue_history.iloc[-1]["end_date"])[:4])
        elapsed_years = max(last_year - first_year, len(revenue_history) - 1)
        revenue_cagr = (
            (revenue_history.iloc[-1]["revenue"] / revenue_history.iloc[0]["revenue"])
            ** (1.0 / elapsed_years) - 1.0
        )
    else:
        revenue_cagr = np.nan
    gross_margins = history["gross_margin"].dropna()
    normalized_gross_margin = float(gross_margins.tail(3).median()) if not gross_margins.empty else np.nan
    gross_margin_mean = float(gross_margins.mean()) if not gross_margins.empty else np.nan
    gross_margin_cv = (
        float(gross_margins.std(ddof=0) / abs(gross_margin_mean))
        if pd.notna(gross_margin_mean) and gross_margin_mean != 0 else np.nan
    )
    latest_gross_margin_delta = (
        float(gross_margins.iloc[-1] - gross_margins.tail(3).median())
        if not gross_margins.empty else np.nan
    )
    latest_bs = bs.iloc[-1] if not bs.empty else pd.Series(dtype=float)
    cash = safe_num(latest_bs.get("money_cap"))
    debt = sum(v for v in [safe_num(latest_bs.get("st_borr")), safe_num(latest_bs.get("lt_borr")), safe_num(latest_bs.get("bond_payable")), safe_num(latest_bs.get("non_cur_liab_due_1y"))] if pd.notna(v))
    net_cash = (0.0 if pd.isna(cash) else cash) - debt
    shares = safe_num(total_shares)
    price = conservative_dcf(normalized, net_cash, shares)
    normalized_fcf = float(history["free_cash_flow"].tail(3).median()) if not history.empty else np.nan
    fcf_conversion = (
        normalized_fcf / normalized
        if pd.notna(normalized_fcf) and pd.notna(normalized) and normalized > 0 else np.nan
    )
    return {
        "financial_years": len(history),
        "owner_earnings_positive_years": owner_positive_years,
        "fcf_positive_years": fcf_positive_years,
        "owner_earnings_cv": owner_cv,
        "normalized_roe": normalized_roe,
        "revenue_cagr": revenue_cagr,
        "normalized_gross_margin": normalized_gross_margin,
        "gross_margin_cv": gross_margin_cv,
        "latest_gross_margin_delta": latest_gross_margin_delta,
        "normalized_owner_earnings": normalized,
        "normalized_fcf": normalized_fcf,
        "normalized_fcf_conversion": fcf_conversion,
        "net_cash": net_cash,
        "owner_earnings_value_per_share": price,
    }


def add_relative_valuation_scores(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    for col in ["pb", "pe_ttm", "ps_ttm", "dv_ratio"]:
        out[col] = pd.to_numeric(out.get(col), errors="coerce")
    group = out.groupby("l1_name", group_keys=False)
    out["pb_value_pct"] = group["pb"].rank(pct=True, ascending=False)
    positive_pe = out["pe_ttm"].where(out["pe_ttm"].gt(0))
    out["pe_value_pct"] = positive_pe.groupby(out["l1_name"]).rank(pct=True, ascending=False)
    out["ps_value_pct"] = group["ps_ttm"].rank(pct=True, ascending=False)
    out["dividend_pct"] = group["dv_ratio"].rank(pct=True, ascending=True)
    out["relative_value_score"] = 100 * (
        0.35 * out["pb_value_pct"].fillna(0)
        + 0.30 * out["pe_value_pct"].fillna(0)
        + 0.20 * out["ps_value_pct"].fillna(0)
        + 0.15 * out["dividend_pct"].fillna(0)
    )
    return out
