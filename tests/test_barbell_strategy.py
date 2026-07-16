import pandas as pd

from portfolio.barbell_strategy import (
    anchor_signal_table,
    build_barbell_weights,
    build_full_market_anchor_universe,
    classify_future_states,
)


POLICY = {"anchor_target": .65, "future_total_cap": .25, "cash_floor": .10,
          "option_seed_weight": .025, "confirmed_build_weight": .05,
          "promoted_core_weight": .075, "single_theme_cap": .15}


def test_unverified_bottom_candidate_is_only_an_option_seed():
    future = pd.DataFrame([{"ts_code": "A", "policy_status": "POLICY_ELIGIBLE", "future_thesis_score": 80, "valuation_gate": "REASONABLE",
                            "financial_check": "PASS_SURVIVAL", "dcf_margin_of_safety": .1,
                            "timing_status": "BOTTOM_HOLD_NO_ADD"}])
    state = classify_future_states(future, pd.DataFrame([{"ts_code": "A"}]))
    assert state.iloc[0]["barbell_state"] == "OPTION_SEED"


def test_core_promotion_requires_all_milestones_and_trend():
    future = pd.DataFrame([{"ts_code": "A", "policy_status": "POLICY_ELIGIBLE", "future_thesis_score": 80, "valuation_gate": "REASONABLE",
                            "financial_check": "PASS_SURVIVAL", "dcf_margin_of_safety": .1,
                            "timing_status": "BOTTOM_VOLUME_CONFIRMATION"}])
    ledger = pd.DataFrame([{"ts_code": "A", "demand_status": "VERIFIED", "profit_pool_status": "VERIFIED",
                            "company_status": "VERIFIED", "invalidation_status": "NONE"}])
    assert classify_future_states(future, ledger).iloc[0]["barbell_state"] == "PROMOTED_CORE"


def test_core_promotion_is_blocked_by_unresolved_caution():
    future = pd.DataFrame([{"ts_code": "A", "policy_status": "POLICY_ELIGIBLE", "future_thesis_score": 80, "valuation_gate": "REASONABLE",
                            "financial_check": "PASS_SURVIVAL", "dcf_margin_of_safety": .1,
                            "timing_status": "BOTTOM_VOLUME_CONFIRMATION"}])
    milestones = pd.DataFrame([{"ts_code": "A", "demand_status": "VERIFIED", "profit_pool_status": "VERIFIED",
                                "company_status": "VERIFIED", "invalidation_status": "NONE"}])
    readiness = pd.DataFrame([{"ts_code": "A", "evidence_status": "SEED_READY_WITH_CAUTION",
                               "seed_evidence_ready": True, "promotion_evidence_ready": False}])
    assert classify_future_states(future, milestones, readiness).iloc[0]["barbell_state"] == "CONFIRMED_BUILD"


def test_two_verified_milestones_use_confirmed_build_step():
    future = pd.DataFrame([{"ts_code": "A", "policy_status": "POLICY_ELIGIBLE", "future_thesis_score": 80,
                            "valuation_gate": "REASONABLE", "financial_check": "PASS_SURVIVAL",
                            "dcf_margin_of_safety": .1, "timing_status": "BOTTOM_VOLUME_CONFIRMATION"}])
    milestones = pd.DataFrame([{"ts_code": "A", "demand_status": "VERIFIED",
                                "profit_pool_status": "VERIFIED", "company_status": "UNVERIFIED",
                                "invalidation_status": "NONE"}])
    readiness = pd.DataFrame([{"ts_code": "A", "evidence_status": "SEED_READY",
                               "seed_evidence_ready": True, "promotion_evidence_ready": True}])
    assert classify_future_states(future, milestones, readiness).iloc[0]["barbell_state"] == "CONFIRMED_BUILD"


def test_option_seed_is_blocked_when_evidence_gate_is_incomplete():
    future = pd.DataFrame([{"ts_code": "A", "policy_status": "POLICY_ELIGIBLE", "future_thesis_score": 80, "valuation_gate": "REASONABLE",
                            "financial_check": "PASS_SURVIVAL", "dcf_margin_of_safety": .1,
                            "timing_status": "BOTTOM_HOLD_NO_ADD"}])
    readiness = pd.DataFrame([{"ts_code": "A", "evidence_status": "EVIDENCE_INCOMPLETE",
                               "seed_evidence_ready": False}])
    state = classify_future_states(future, pd.DataFrame([{"ts_code": "A"}]), readiness).iloc[0]
    assert state["barbell_state"] == "RESEARCH_ONLY"
    assert state["state_reason"] == "seed evidence gate failed: EVIDENCE_INCOMPLETE"


def test_option_seed_passes_when_auditable_evidence_is_ready():
    future = pd.DataFrame([{"ts_code": "A", "policy_status": "POLICY_ELIGIBLE", "future_thesis_score": 80, "valuation_gate": "REASONABLE",
                            "financial_check": "PASS_SURVIVAL", "dcf_margin_of_safety": .1,
                            "timing_status": "BOTTOM_HOLD_NO_ADD"}])
    readiness = pd.DataFrame([{"ts_code": "A", "evidence_status": "SEED_READY",
                               "seed_evidence_ready": True}])
    assert classify_future_states(future, pd.DataFrame([{"ts_code": "A"}]), readiness).iloc[0]["barbell_state"] == "OPTION_SEED"


def test_unapproved_anchor_budget_remains_cash():
    anchors = pd.DataFrame([{"ts_code": "B", "defensive_status": "WATCH"}])
    future = pd.DataFrame(columns=["barbell_state"])
    _, summary = build_barbell_weights(anchors, future, POLICY)
    assert summary["cash_weight"] == 1.0


def test_seed_and_core_weights_are_different():
    anchors = pd.DataFrame(columns=["defensive_status"])
    future = pd.DataFrame([
        {"ts_code": "A", "name": "A", "theme": "x", "barbell_state": "OPTION_SEED", "future_thesis_score": 80, "state_reason": "seed"},
        {"ts_code": "B", "name": "B", "theme": "y", "barbell_state": "PROMOTED_CORE", "future_thesis_score": 80, "state_reason": "core"},
    ])
    portfolio, _ = build_barbell_weights(anchors, future, POLICY)
    weights = portfolio.set_index("ts_code")["target_weight"]
    assert weights["A"] == .025
    assert weights["B"] == .075


def test_confirmed_build_receives_five_percent():
    anchors = pd.DataFrame(columns=["defensive_status"])
    future = pd.DataFrame([{
        "ts_code": "A", "name": "A", "theme": "x", "barbell_state": "CONFIRMED_BUILD",
        "future_thesis_score": 80, "state_reason": "build",
    }])
    portfolio, summary = build_barbell_weights(anchors, future, POLICY)
    assert portfolio.iloc[0]["target_weight"] == .05
    assert summary["confirmed_build_weight"] == .05


def test_option_seed_total_is_capped_at_ten_percent():
    anchors = pd.DataFrame(columns=["defensive_status"])
    future = pd.DataFrame([
        {"ts_code": str(i), "name": str(i), "theme": f"theme-{i}", "barbell_state": "OPTION_SEED",
         "future_thesis_score": 90 - i, "state_reason": "seed"}
        for i in range(6)
    ])
    policy = {**POLICY, "option_seed_target_min": .075, "option_seed_total_cap": .10}
    portfolio, summary = build_barbell_weights(anchors, future, policy)
    assert abs(portfolio["target_weight"].sum() - .10) < 1e-12
    assert len(portfolio) == 4
    assert summary["option_seed_target_status"] == "WITHIN_TARGET"


def test_anchor_requires_positive_cash_earnings_even_when_moat_is_approved():
    daily = pd.DataFrame([{"ts_code": "A", "dv_ratio": 4.0}])
    watch = pd.DataFrame([{"ts_code": "A", "name": "A", "moat_approved": "TRUE"}])
    financials = pd.DataFrame([{"ts_code": "A", "owner_earnings_yield": .05,
                                "normalized_owner_earnings": 10, "normalized_fcf": -1}])
    assert anchor_signal_table(daily, watch, financials).iloc[0]["defensive_status"] == "WATCH"


def test_auto_anchor_does_not_require_manual_moat_flag():
    daily = pd.DataFrame([{"ts_code": "A", "dv_ratio": 4.0, "pe_ttm": 10.0}])
    watch = pd.DataFrame([{"ts_code": "A", "name": "A", "moat_approved": "FALSE"}])
    financials = pd.DataFrame([{"ts_code": "A", "owner_earnings_yield": .05,
                                "normalized_owner_earnings": 10, "normalized_fcf": 8, "net_cash": 1}])
    policy = {"anchor_selection_mode": "auto"}
    assert anchor_signal_table(daily, watch, financials, policy).iloc[0]["defensive_status"] == "DEFENSIVE_ELIGIBLE"


def test_approved_anchor_cannot_also_receive_future_weight():
    anchors = pd.DataFrame([{"ts_code": "A", "name": "A", "defensive_status": "DEFENSIVE_ELIGIBLE"}])
    future = pd.DataFrame([{"ts_code": "A", "name": "A", "theme": "x", "barbell_state": "OPTION_SEED",
                            "future_thesis_score": 90, "state_reason": "seed"}])
    portfolio, _ = build_barbell_weights(anchors, future, POLICY)
    assert len(portfolio[portfolio["ts_code"].eq("A")]) == 1
    assert portfolio.iloc[0]["allocation_bucket"] == "ANCHOR"


def test_full_market_anchor_universe_applies_first_pass_and_industry_cap():
    daily = pd.DataFrame([
        {"ts_code": "A", "trade_date": 20260713, "pe_ttm": 10, "pb": 1, "dv_ratio": 4, "total_mv": 2_000_000},
        {"ts_code": "B", "trade_date": 20260713, "pe_ttm": 10, "pb": 1, "dv_ratio": 4, "total_mv": 2_000_000},
        {"ts_code": "C", "trade_date": 20260713, "pe_ttm": 10, "pb": 1, "dv_ratio": 1, "total_mv": 2_000_000},
    ])
    master = pd.DataFrame([
        {"ts_code": code, "name": code, "list_date": "2010-01-01", "list_status": "L"}
        for code in ["A", "B", "C"]
    ])
    members = pd.DataFrame([{"ts_code": code, "l1_name": "消费"} for code in ["A", "B", "C"]])
    policy = {"anchor_min_dividend_yield": 2.5, "anchor_max_pe_ttm": 30, "anchor_max_pb": 6,
              "anchor_min_market_cap_yi": 100, "anchor_min_listing_years": 5,
              "anchor_preselect_per_industry": 1, "anchor_financial_shortlist_size": 10}
    funnel, shortlist = build_full_market_anchor_universe(daily, master, members, policy)
    assert len(shortlist) == 1
    assert funnel.set_index("ts_code").loc["C", "preselection_status"] == "DIVIDEND_FAIL"


def test_auto_anchor_rejects_low_roe_or_unstable_owner_earnings():
    daily = pd.DataFrame([
        {"ts_code": "LOW", "dv_ratio": 4.0, "pe_ttm": 10.0},
        {"ts_code": "VOL", "dv_ratio": 4.0, "pe_ttm": 10.0},
    ])
    watch = pd.DataFrame([
        {"ts_code": "LOW", "name": "low", "moat_approved": False},
        {"ts_code": "VOL", "name": "volatile", "moat_approved": False},
    ])
    common = {"owner_earnings_yield": .05, "normalized_owner_earnings": 10,
              "normalized_fcf": 8, "net_cash": 1, "financial_years": 5,
              "owner_earnings_positive_years": 5, "fcf_positive_years": 5}
    financials = pd.DataFrame([
        {"ts_code": "LOW", **common, "normalized_roe": .05, "owner_earnings_cv": .10},
        {"ts_code": "VOL", **common, "normalized_roe": .20, "owner_earnings_cv": .80},
    ])
    policy = {"anchor_selection_mode": "auto", "anchor_min_normalized_roe": .08,
              "anchor_max_owner_earnings_cv": .50}
    result = anchor_signal_table(daily, watch, financials, policy)
    assert result["defensive_status"].eq("WATCH").all()


def test_anchor_moat_proxy_requires_industry_position_and_durable_pricing_or_scale():
    daily = pd.DataFrame([
        {"ts_code": "LEADER", "dv_ratio": 4.0, "pe_ttm": 12.0},
        {"ts_code": "FOLLOWER", "dv_ratio": 4.0, "pe_ttm": 12.0},
    ])
    watch = pd.DataFrame([
        {"ts_code": "LEADER", "name": "leader", "moat_approved": False,
         "l1_name": "食品饮料", "l2_name": "饮料", "l3_name": "品牌饮料",
         "subindustry_market_cap_rank": 1},
        {"ts_code": "FOLLOWER", "name": "follower", "moat_approved": False,
         "l1_name": "食品饮料", "l2_name": "饮料", "l3_name": "品牌饮料",
         "subindustry_market_cap_rank": 6},
    ])
    common = {
        "owner_earnings_yield": .06, "normalized_owner_earnings": 10,
        "normalized_fcf": 8, "normalized_fcf_conversion": .8, "net_cash": 1,
        "financial_years": 5, "owner_earnings_positive_years": 5,
        "fcf_positive_years": 5, "normalized_roe": .22,
        "owner_earnings_cv": .12, "revenue_cagr": .05,
        "normalized_gross_margin": .55, "gross_margin_cv": .04,
        "latest_gross_margin_delta": -.01,
    }
    financials = pd.DataFrame([
        {"ts_code": "LEADER", **common},
        {"ts_code": "FOLLOWER", **common},
    ])
    policy = {
        "anchor_selection_mode": "auto", "anchor_require_moat_proxy": True,
        "anchor_max_subindustry_market_cap_rank": 3,
        "anchor_max_gross_margin_cv": .15, "anchor_min_revenue_cagr": -.03,
        "anchor_min_gross_margin_delta": -.03, "anchor_min_fcf_conversion": .5,
        "anchor_max_dividend_payout_proxy": 1.1,
    }
    result = anchor_signal_table(daily, watch, financials, policy).set_index("ts_code")
    assert result.loc["LEADER", "defensive_status"] == "DEFENSIVE_ELIGIBLE"
    assert result.loc["LEADER", "moat_proxy_type"] == "BRAND_PRICING_POWER_PROXY"
    assert result.loc["FOLLOWER", "defensive_status"] == "WATCH"
    assert result.loc["FOLLOWER", "first_failed_anchor_gate"] == "MOAT_PROXY_FAIL"


def test_anchor_allocation_diversifies_economic_factors_before_adding_second_name():
    anchors = pd.DataFrame([
        {"ts_code": "A1", "name": "A1", "l1_name": "消费", "economic_factor": "A",
         "anchor_score": 100, "defensive_status": "DEFENSIVE_ELIGIBLE"},
        {"ts_code": "A2", "name": "A2", "l1_name": "消费", "economic_factor": "A",
         "anchor_score": 99, "defensive_status": "DEFENSIVE_ELIGIBLE"},
        {"ts_code": "A3", "name": "A3", "l1_name": "消费", "economic_factor": "A",
         "anchor_score": 98, "defensive_status": "DEFENSIVE_ELIGIBLE"},
        {"ts_code": "B1", "name": "B1", "l1_name": "工业", "economic_factor": "B",
         "anchor_score": 80, "defensive_status": "DEFENSIVE_ELIGIBLE"},
        {"ts_code": "C1", "name": "C1", "l1_name": "医疗", "economic_factor": "C",
         "anchor_score": 70, "defensive_status": "DEFENSIVE_ELIGIBLE"},
        {"ts_code": "D1", "name": "D1", "l1_name": "数字", "economic_factor": "D",
         "anchor_score": 60, "defensive_status": "DEFENSIVE_ELIGIBLE"},
    ])
    policy = {**POLICY, "anchor_max_names": 6, "anchor_max_weight": .15,
              "anchor_industry_cap": .20, "anchor_economic_factor_cap": .20}
    portfolio, summary = build_barbell_weights(anchors, pd.DataFrame(columns=["barbell_state"]), policy)
    factor_weights = portfolio.groupby(portfolio["ts_code"].str[0])["target_weight"].sum()
    assert set("BCD").issubset(set(portfolio["ts_code"].str[0]))
    assert factor_weights.max() <= .20 + 1e-12
    assert abs(summary["anchor_weight"] - .65) < 1e-12
