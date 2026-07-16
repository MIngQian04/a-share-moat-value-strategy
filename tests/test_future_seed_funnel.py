import pandas as pd

from scripts.run_barbell_strategy import build_future_research_funnel


def base(**overrides) -> dict:
    row = {
        "ts_code": "A",
        "policy_code": "NET_ENERGY",
        "policy_status": "POLICY_ELIGIBLE",
        "future_thesis_score": 80,
        "financial_check": "PASS_SURVIVAL",
        "valuation_gate": "REASONABLE",
        "dcf_margin_of_safety": .1,
        "timing_status": "BOTTOM_HOLD_NO_ADD",
        "evidence_status": "SEED_READY",
        "barbell_state": "OPTION_SEED",
    }
    row.update(overrides)
    return row


def test_funnel_reports_first_failed_gate_in_strategy_order():
    frame = pd.DataFrame([
        base(ts_code="seed"),
        base(ts_code="value", barbell_state="RESEARCH_ONLY", dcf_margin_of_safety=-.1),
        base(ts_code="cash", barbell_state="RESEARCH_ONLY", financial_check="FAIL_CASH_EARNINGS"),
        base(ts_code="thesis", barbell_state="RESEARCH_ONLY", future_thesis_score=60),
    ])
    result = build_future_research_funnel(frame).set_index("ts_code")
    assert result.loc["seed", "first_failed_gate"] == "OPTION_SEED"
    assert result.loc["value", "first_failed_gate"] == "VALUE_UNSUPPORTED"
    assert result.loc["cash", "first_failed_gate"] == "CASH_EARNINGS_FAIL"
    assert result.loc["thesis", "first_failed_gate"] == "THESIS_BELOW_72"
