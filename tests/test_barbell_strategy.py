import pandas as pd
import pytest

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


def test_held_seed_survives_a_modest_dcf_premium_with_additions_frozen():
    future = pd.DataFrame([{
        "ts_code": "A", "policy_status": "POLICY_ELIGIBLE", "future_thesis_score": 80,
        "valuation_gate": "REASONABLE", "financial_check": "PASS_SURVIVAL",
        "dcf_margin_of_safety": -.05, "timing_status": "BOTTOM_HOLD_NO_ADD",
        "profit_growth_avg": .10, "profit_loss_to_profit": False,
    }])
    readiness = pd.DataFrame([{"ts_code": "A", "evidence_status": "SEED_READY",
                               "seed_evidence_ready": True, "promotion_evidence_ready": True}])
    previous = pd.DataFrame([{"ts_code": "A", "allocation_bucket": "FUTURE",
                              "target_weight": .025, "strategy_state": "OPTION_SEED"}])
    state = classify_future_states(
        future, pd.DataFrame([{"ts_code": "A"}]), readiness,
        previous_portfolio=previous, as_of="2026-07-17",
        policy={"seed_valuation_premium_factor": .8},
    ).iloc[0]
    assert state["barbell_state"] == "OPTION_SEED"
    assert state["valuation_warning_status"] == "WITHIN_TOLERANCE"


def test_persistent_seed_premium_reduces_one_ladder_step_after_warning():
    future = pd.DataFrame([{
        "ts_code": "A", "name": "A", "policy_status": "POLICY_ELIGIBLE", "future_thesis_score": 80,
        "valuation_gate": "REASONABLE", "financial_check": "PASS_SURVIVAL",
        "dcf_margin_of_safety": -.15, "timing_status": "BOTTOM_HOLD_NO_ADD",
        "profit_growth_avg": .10, "profit_loss_to_profit": False,
    }])
    readiness = pd.DataFrame([{"ts_code": "A", "evidence_status": "SEED_READY",
                               "seed_evidence_ready": True, "promotion_evidence_ready": True}])
    previous = pd.DataFrame([{"ts_code": "A", "allocation_bucket": "FUTURE",
                              "target_weight": .05, "strategy_state": "CONFIRMED_BUILD"}])
    warnings = pd.DataFrame([{"ts_code": "A", "warning_date": "2026-07-16",
                              "status": "WARNING", "consecutive_days": 1}])
    state = classify_future_states(
        future, pd.DataFrame([{"ts_code": "A"}]), readiness,
        previous_portfolio=previous, valuation_warnings=warnings,
        as_of="2026-07-17", policy={"seed_valuation_premium_factor": .8},
    )
    assert state.iloc[0]["barbell_state"] == "VALUATION_REDUCTION"
    portfolio, _ = build_barbell_weights(
        pd.DataFrame(columns=["defensive_status"]), state,
        {**POLICY, "option_seed_weight": .025}, previous_portfolio=previous,
    )
    assert portfolio.iloc[0]["target_weight"] == .025


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


def test_new_anchor_requires_positive_base_dcf_when_policy_enables_it():
    daily = pd.DataFrame([{"ts_code": "A", "dv_ratio": 4.0, "pe_ttm": 10.0}])
    watch = pd.DataFrame([{"ts_code": "A", "name": "A", "moat_approved": "FALSE"}])
    financials = pd.DataFrame([{
        "ts_code": "A", "owner_earnings_yield": .05, "normalized_owner_earnings": 10,
        "normalized_fcf": 8, "net_cash": 1, "dcf_base_margin_of_safety": -.05,
        "dcf_optimistic_margin_of_safety": .06,
    }])
    result = anchor_signal_table(
        daily, watch, financials,
        {"anchor_selection_mode": "auto", "anchor_require_dcf_base": True},
    ).iloc[0]
    assert result["defensive_status"] == "WATCH"
    assert result["first_failed_anchor_gate"] == "DCF_BASE_VALUE_FAIL"
    assert result["anchor_dcf_status"] == "PREMIUM_WITHIN_OPTIMISTIC"


def test_existing_anchor_inside_optimistic_dcf_is_held_without_additions():
    anchors = pd.DataFrame([{
        "ts_code": "A", "name": "A", "defensive_status": "WATCH",
        "anchor_dcf_status": "PREMIUM_WITHIN_OPTIMISTIC", "l1_name": "消费",
        "economic_factor": "CONSUMPTION",
    }])
    previous = pd.DataFrame([{"ts_code": "A", "name": "A", "allocation_bucket": "ANCHOR", "target_weight": .15}])
    portfolio, _ = build_barbell_weights(
        anchors, pd.DataFrame(columns=["barbell_state"]),
        {**POLICY, "anchor_sticky": True, "anchor_min_weight": .025, "anchor_reduction_step": .025},
        previous_portfolio=previous, as_of="2026-07-17",
    )
    row = portfolio.iloc[0]
    assert row["target_weight"] == .15
    assert "暂停加仓" in row["reason"]


def test_anchor_above_optimistic_dcf_warns_then_reduces_one_step():
    anchors = pd.DataFrame([{
        "ts_code": "A", "name": "A", "defensive_status": "WATCH",
        "anchor_dcf_status": "OVER_OPTIMISTIC", "l1_name": "消费",
        "economic_factor": "CONSUMPTION",
    }])
    previous = pd.DataFrame([{"ts_code": "A", "name": "A", "allocation_bucket": "ANCHOR", "target_weight": .15}])
    policy = {**POLICY, "anchor_sticky": True, "anchor_min_weight": .025, "anchor_reduction_step": .025}
    first, _ = build_barbell_weights(
        anchors, pd.DataFrame(columns=["barbell_state"]), policy,
        previous_portfolio=previous, as_of="2026-07-17",
    )
    assert first.iloc[0]["target_weight"] == .15
    assert "预警" in first.iloc[0]["reason"]
    warnings = pd.DataFrame([{"ts_code": "A", "warning_date": "2026-07-16", "status": "WARNING"}])
    second, _ = build_barbell_weights(
        anchors, pd.DataFrame(columns=["barbell_state"]), policy,
        previous_portfolio=previous, anchor_valuation_warnings=warnings,
        as_of="2026-07-17",
    )
    assert second.iloc[0]["target_weight"] == .125
    assert "减仓" in second.iloc[0]["reason"]


def test_manual_anchor_override_releases_weight_to_cash():
    anchors = pd.DataFrame([{
        "ts_code": "000786.SZ", "name": "北新建材", "defensive_status": "DEFENSIVE_ELIGIBLE",
        "anchor_dcf_status": "BASE_SUPPORTED", "l1_name": "建筑材料",
        "economic_factor": "INDUSTRIAL_CAPEX",
    }])
    previous = pd.DataFrame([{
        "ts_code": "000786.SZ", "name": "北新建材", "allocation_bucket": "ANCHOR",
        "target_weight": .15,
    }])
    policy = {**POLICY, "anchor_sticky": True, "anchor_max_names": 1,
              "manual_anchor_overrides": [{
                  "ts_code": "000786.SZ", "target_weight": .10,
                  "effective_date": "20260720", "reason": "人工研究降仓",
              }]}
    portfolio, summary = build_barbell_weights(
        anchors, pd.DataFrame(columns=["barbell_state"]), policy,
        previous_portfolio=previous, as_of="20260720",
    )
    row = portfolio.iloc[0]
    assert row["target_weight"] == .10
    assert row["reason"] == "人工研究降仓"
    assert summary["cash_weight"] == .90


def test_manual_future_override_promotes_with_explicit_reason():
    future = pd.DataFrame([{
        "ts_code": "600941.SH", "name": "中国移动", "policy_status": "POLICY_ELIGIBLE",
        "future_thesis_score": 88, "valuation_gate": "REASONABLE",
        "financial_check": "PASS_SURVIVAL", "dcf_margin_of_safety": .20,
        "timing_status": "BOTTOM_HOLD_NO_ADD",
    }])
    milestones = pd.DataFrame([{
        "ts_code": "600941.SH", "demand_status": "VERIFIED",
        "profit_pool_status": "VERIFIED", "company_status": "VERIFIED",
        "invalidation_status": "NONE",
    }])
    state = classify_future_states(
        future, milestones,
        evidence_readiness=pd.DataFrame([{
            "ts_code": "600941.SH", "evidence_status": "SEED_READY",
            "seed_evidence_ready": True, "promotion_evidence_ready": True,
        }]),
        as_of="2026-07-17",
        policy={"manual_future_overrides": [{
            "ts_code": "600941.SH", "target_weight": .075,
            "strategy_state": "PROMOTED_CORE", "effective_date": "2026-07-17",
            "reason": "人工确认中国移动",
        }]},
    )
    assert state.iloc[0]["barbell_state"] == "PROMOTED_CORE"
    assert state.iloc[0]["manual_override"]
    assert state.iloc[0]["state_reason"] == "人工确认中国移动"


def test_approved_anchor_cannot_also_receive_future_weight():
    anchors = pd.DataFrame([{"ts_code": "A", "name": "A", "defensive_status": "DEFENSIVE_ELIGIBLE"}])
    future = pd.DataFrame([{"ts_code": "A", "name": "A", "theme": "x", "barbell_state": "OPTION_SEED",
                            "future_thesis_score": 90, "state_reason": "seed"}])
    portfolio, _ = build_barbell_weights(anchors, future, POLICY)
    assert len(portfolio[portfolio["ts_code"].eq("A")]) == 1
    assert portfolio.iloc[0]["allocation_bucket"] == "ANCHOR"


def test_sticky_anchor_does_not_replace_gree_with_a_small_score_leader():
    anchors = pd.DataFrame([
        {"ts_code": "000651.SZ", "name": "格力电器", "defensive_status": "DEFENSIVE_ELIGIBLE",
         "anchor_score": 71.56, "l1_name": "家用电器", "economic_factor": "DOMESTIC_CONSUMPTION"},
        {"ts_code": "603195.SH", "name": "公牛集团", "defensive_status": "DEFENSIVE_ELIGIBLE",
         "anchor_score": 71.71, "l1_name": "家用电器", "economic_factor": "DOMESTIC_CONSUMPTION"},
    ])
    previous = pd.DataFrame([{
        "date": "2026-07-16", "ts_code": "000651.SZ", "name": "格力电器",
        "allocation_bucket": "ANCHOR", "target_weight": .064865, "close": 39.83,
    }])
    policy = {**POLICY, "anchor_target": .10, "anchor_max_names": 1,
              "anchor_entry_weight": .025, "anchor_sticky": True}
    portfolio, _ = build_barbell_weights(anchors, pd.DataFrame(columns=["barbell_state"]), policy, previous)
    weights = portfolio.set_index("ts_code")["target_weight"]
    assert weights["000651.SZ"] == .064865
    assert "603195.SH" not in weights


def test_sticky_anchor_reduces_in_steps_but_never_auto_clears():
    anchors = pd.DataFrame([{
        "ts_code": "000651.SZ", "name": "格力电器", "defensive_status": "WATCH",
        "anchor_score": 20, "l1_name": "家用电器", "economic_factor": "DOMESTIC_CONSUMPTION",
    }])
    previous = pd.DataFrame([{
        "date": "2026-07-16", "ts_code": "000651.SZ", "name": "格力电器",
        "allocation_bucket": "ANCHOR", "target_weight": .064865, "close": 39.83,
    }])
    portfolio, _ = build_barbell_weights(anchors, pd.DataFrame(columns=["barbell_state"]), POLICY, previous)
    row = portfolio.loc[portfolio["ts_code"].eq("000651.SZ")].iloc[0]
    assert row["target_weight"] == pytest.approx(.039865)
    assert row["target_weight"] >= POLICY.get("anchor_min_weight", .025)
    assert "不自动清仓" in row["reason"]


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
