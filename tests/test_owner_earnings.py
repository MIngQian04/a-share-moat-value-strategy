import pandas as pd

from valuation.owner_earnings import conservative_dcf, owner_earnings_from_statements


def test_owner_earnings_exposes_pricing_power_and_cash_conversion_metrics():
    years = ["20221231", "20231231", "20241231"]
    income = pd.DataFrame({
        "end_date": years,
        "ann_date": ["20230331", "20240331", "20250331"],
        "revenue": [100.0, 110.0, 121.0],
        "oper_cost": [50.0, 55.0, 60.5],
        "n_income_attr_p": [20.0, 22.0, 24.2],
    })
    cashflow = pd.DataFrame({
        "end_date": years,
        "ann_date": ["20230331", "20240331", "20250331"],
        "n_cashflow_act": [24.0, 26.4, 29.04],
        "c_pay_acq_const_fiolta": [4.0, 4.4, 4.84],
        "depr_fa_coga_dpba": [4.0, 4.4, 4.84],
        "amort_intang_assets": [0.0, 0.0, 0.0],
        "lt_amort_deferred_exp": [0.0, 0.0, 0.0],
    })
    balance = pd.DataFrame({
        "end_date": years,
        "ann_date": ["20230331", "20240331", "20250331"],
        "total_hldr_eqy_exc_min_int": [80.0, 88.0, 96.8],
        "money_cap": [10.0, 11.0, 12.1],
        "st_borr": [0.0, 0.0, 0.0],
        "lt_borr": [0.0, 0.0, 0.0],
        "bond_payable": [0.0, 0.0, 0.0],
        "non_cur_liab_due_1y": [0.0, 0.0, 0.0],
    })

    result = owner_earnings_from_statements(income, cashflow, balance, total_shares=10.0)

    assert abs(result["revenue_cagr"] - .10) < 1e-12
    assert abs(result["normalized_gross_margin"] - .50) < 1e-12
    assert result["gross_margin_cv"] < 1e-12
    assert result["normalized_fcf_conversion"] > .8


def test_owner_earnings_exposes_five_discount_rate_sensitivities():
    income = pd.DataFrame({
        "end_date": ["20221231", "20231231", "20241231"],
        "ann_date": ["20230331", "20240331", "20250331"],
        "revenue": [100.0, 110.0, 121.0],
        "oper_cost": [50.0, 55.0, 60.5],
        "n_income_attr_p": [20.0, 22.0, 24.2],
    })
    cashflow = pd.DataFrame({
        "end_date": ["20221231", "20231231", "20241231"],
        "ann_date": ["20230331", "20240331", "20250331"],
        "n_cashflow_act": [24.0, 26.4, 29.04],
        "c_pay_acq_const_fiolta": [4.0, 4.4, 4.84],
        "depr_fa_coga_dpba": [4.0, 4.4, 4.84],
        "amort_intang_assets": [0.0, 0.0, 0.0],
        "lt_amort_deferred_exp": [0.0, 0.0, 0.0],
    })
    balance = pd.DataFrame({
        "end_date": ["20221231", "20231231", "20241231"],
        "ann_date": ["20230331", "20240331", "20250331"],
        "total_hldr_eqy_exc_min_int": [80.0, 88.0, 96.8],
        "money_cap": [10.0, 11.0, 12.1],
        "st_borr": [0.0, 0.0, 0.0],
        "lt_borr": [0.0, 0.0, 0.0],
        "bond_payable": [0.0, 0.0, 0.0],
        "non_cur_liab_due_1y": [0.0, 0.0, 0.0],
    })

    result = owner_earnings_from_statements(income, cashflow, balance, total_shares=10.0)
    rates = [result[f"dcf_{name}_discount_rate"] for name in [
        "very_optimistic", "optimistic", "base", "cautious", "very_pessimistic"
    ]]
    values = [result[f"dcf_{name}_value_per_share"] for name in [
        "very_optimistic", "optimistic", "base", "cautious", "very_pessimistic"
    ]]
    assert rates == [0.08, 0.09, 0.10, 0.11, 0.12]
    assert values[0] > values[1] > values[2] > values[3] > values[4]
    assert result["owner_earnings_value_per_share"] == result["dcf_base_value_per_share"]
