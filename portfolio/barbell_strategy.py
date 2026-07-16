from __future__ import annotations

import numpy as np
import pandas as pd


MILESTONE_COLUMNS = ["demand_status", "profit_pool_status", "company_status"]


def assign_anchor_economic_factors(frame: pd.DataFrame) -> pd.Series:
    """Group anchors by shared economic risk rather than only SW industry names."""
    l1 = frame.get("l1_name", pd.Series("", index=frame.index)).fillna("").astype(str)
    l2 = frame.get("l2_name", pd.Series("", index=frame.index)).fillna("").astype(str)
    l3 = frame.get("l3_name", pd.Series("", index=frame.index)).fillna("").astype(str)
    factor = pd.Series("DOMESTIC_CONSUMPTION", index=frame.index, dtype=object)
    factor.loc[l1.eq("医药生物")] = "HEALTHCARE"
    factor.loc[l1.isin({"汽车", "交通运输"})] = "MOBILITY_LOGISTICS"
    factor.loc[l1.isin({"机械设备", "建筑装饰", "建筑材料", "电力设备", "国防军工", "环保"})] = "INDUSTRIAL_CAPEX"
    factor.loc[l1.isin({"传媒", "计算机", "通信"}) | (l1.eq("电子") & ~l3.eq("品牌消费电子"))] = "DIGITAL_SERVICES"
    factor.loc[l2.isin({"纺织制造", "贸易Ⅱ"}) | l3.isin({"跨境物流", "品牌消费电子"})] = "EXPORT_MANUFACTURING"
    return factor


def build_full_market_anchor_universe(
    daily_basic: pd.DataFrame,
    security_master: pd.DataFrame,
    sw_members: pd.DataFrame,
    policy: dict,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run a cheap, auditable first pass over every currently traded A share."""
    market = daily_basic.copy()
    master_fields = [c for c in ["ts_code", "name", "list_date", "list_status"] if c in security_master]
    industry_fields = [c for c in ["ts_code", "l1_name", "l2_name", "l3_name"] if c in sw_members]
    market = market.merge(security_master[master_fields].drop_duplicates("ts_code"), on="ts_code", how="left")
    market = market.merge(sw_members[industry_fields].drop_duplicates("ts_code"), on="ts_code", how="left")

    trade_date = pd.to_datetime(
        pd.to_numeric(market["trade_date"], errors="coerce").astype("Int64").astype(str),
        format="%Y%m%d", errors="coerce",
    )
    list_date = pd.to_datetime(market.get("list_date"), errors="coerce")
    market["listing_years"] = (trade_date - list_date).dt.days / 365.25
    market["market_cap_yi"] = pd.to_numeric(market.get("total_mv"), errors="coerce") / 10000.0
    pe = pd.to_numeric(market.get("pe_ttm"), errors="coerce")
    pb = pd.to_numeric(market.get("pb"), errors="coerce")
    dividend = pd.to_numeric(market.get("dv_ratio"), errors="coerce")
    excluded = set(policy.get("anchor_excluded_industries", ["银行", "非银金融"]))
    excluded_l2_industries = set(policy.get("anchor_excluded_l2_industries", []))
    excluded_subindustries = set(policy.get("anchor_excluded_subindustries", []))
    subindustry = market.get("l3_name", pd.Series("", index=market.index)).fillna("")
    subindustry = subindustry.where(subindustry.ne(""), market.get("l2_name", pd.Series("", index=market.index)).fillna(""))
    subindustry = subindustry.where(subindustry.ne(""), market.get("l1_name", pd.Series("未分类", index=market.index)).fillna("未分类"))
    market["anchor_subindustry"] = subindustry
    market["subindustry_market_cap_rank"] = market.groupby("anchor_subindustry")["total_mv"].rank(
        method="min", ascending=False
    )
    market["subindustry_market_cap_pct"] = market.groupby("anchor_subindustry")["total_mv"].rank(
        pct=True, ascending=True
    )
    gates = {
        "NOT_ACTIVE": ~market.get("list_status", pd.Series("L", index=market.index)).fillna("").eq("L"),
        "ST_OR_DELIST_RISK": market.get("name", pd.Series("", index=market.index)).fillna("").str.contains(r"ST|退", regex=True),
        "MISSING_INDUSTRY": market.get("l1_name", pd.Series(index=market.index, dtype=object)).isna(),
        "SECTOR_MODEL_UNSUPPORTED": market.get("l1_name", pd.Series(index=market.index, dtype=object)).isin(excluded),
        "SUBSECTOR_MODEL_UNSUPPORTED": market.get("l2_name", pd.Series(index=market.index, dtype=object)).isin(excluded_l2_industries),
        "CYCLICAL_SUBINDUSTRY": market.get("l3_name", pd.Series(index=market.index, dtype=object)).isin(excluded_subindustries),
        "TOO_NEW": market["listing_years"].lt(float(policy.get("anchor_min_listing_years", 5))),
        "TOO_SMALL": market["market_cap_yi"].lt(float(policy.get("anchor_min_market_cap_yi", 100))),
        "DIVIDEND_FAIL": dividend.lt(float(policy.get("anchor_min_dividend_yield", 2.5))) | dividend.isna(),
        "PE_FAIL": ~pe.gt(0) | pe.gt(float(policy.get("anchor_max_pe_ttm", 30))),
        "PB_FAIL": ~pb.gt(0) | pb.gt(float(policy.get("anchor_max_pb", 6))),
    }
    market["preselection_status"] = "PRELIMINARY_PASS"
    for reason, failed in gates.items():
        market.loc[market["preselection_status"].eq("PRELIMINARY_PASS") & failed, "preselection_status"] = reason

    earnings_yield = 1.0 / pe.where(pe.gt(0))
    cap_score = np.log1p(market["market_cap_yi"].clip(lower=0)) / np.log1p(5000)
    market["preliminary_anchor_score"] = 100 * (
        0.35 * (dividend.clip(0, 8) / 8)
        + 0.35 * (earnings_yield.clip(0, 0.12) / 0.12)
        + 0.15 * (1 - pb.clip(0, float(policy.get("anchor_max_pb", 6))) / float(policy.get("anchor_max_pb", 6)))
        + 0.15 * cap_score.clip(0, 1)
    )
    passed = market[market["preselection_status"].eq("PRELIMINARY_PASS")].sort_values(
        ["preliminary_anchor_score", "ts_code"], ascending=[False, True]
    )
    per_industry = int(policy.get("anchor_preselect_per_industry", 8))
    limit = int(policy.get("anchor_financial_shortlist_size", 120))
    shortlist = passed.groupby("l1_name", group_keys=False).head(per_industry).head(limit).copy()
    shortlist["moat_approved"] = False
    market.loc[shortlist.index, "preselection_status"] = "FINANCIAL_SHORTLIST"
    market.loc[market["preselection_status"].eq("PRELIMINARY_PASS"), "preselection_status"] = "PASS_NOT_SHORTLISTED"
    return market.sort_values("preliminary_anchor_score", ascending=False, na_position="last"), shortlist


def anchor_signal_table(daily_basic: pd.DataFrame, watchlist: pd.DataFrame,
                        financials: pd.DataFrame, policy: dict | None = None) -> pd.DataFrame:
    """Screen financial quality, industry position and durable pricing-power proxies."""
    required = {"ts_code", "name", "moat_approved"}
    missing = required - set(watchlist.columns)
    if missing:
        raise ValueError(f"anchor watchlist missing columns: {sorted(missing)}")
    market_fields = ["ts_code", *[
        c for c in ["l1_name", "close", "pe_ttm", "pb", "dv_ratio", "total_mv"]
        if c in daily_basic and c not in watchlist
    ]]
    out = watchlist.merge(daily_basic[market_fields], on="ts_code", how="left")
    if not financials.empty and "ts_code" in financials:
        out = out.merge(financials, on="ts_code", how="left")
    out["moat_approved"] = out["moat_approved"].astype(str).str.upper().eq("TRUE")
    policy = policy or {}
    auto_mode = str(policy.get("anchor_selection_mode", "manual")).lower() == "auto"
    min_dividend = float(policy.get("anchor_min_dividend_yield", 2.5))
    min_owner_yield = float(policy.get("anchor_min_owner_earnings_yield", 0.03))
    max_debt_ratio = float(policy.get("anchor_max_net_debt_to_owner_earnings", 6.0))
    max_owner_cv = float(policy.get("anchor_max_owner_earnings_cv", np.inf))
    min_roe = float(policy.get("anchor_min_normalized_roe", 0.0))
    max_pe = float(policy.get("anchor_max_pe_ttm", 30.0))
    min_revenue_cagr = float(policy.get("anchor_min_revenue_cagr", -np.inf))
    max_gross_margin_cv = float(policy.get("anchor_max_gross_margin_cv", np.inf))
    min_gross_margin_delta = float(policy.get("anchor_min_gross_margin_delta", -np.inf))
    min_fcf_conversion = float(policy.get("anchor_min_fcf_conversion", -np.inf))
    max_payout_proxy = float(policy.get("anchor_max_dividend_payout_proxy", np.inf))
    max_subindustry_rank = float(policy.get("anchor_max_subindustry_market_cap_rank", np.inf))
    brand_gross_margin = float(policy.get("anchor_brand_min_gross_margin", 0.30))
    brand_roe = float(policy.get("anchor_brand_min_roe", 0.15))
    scale_roe = float(policy.get("anchor_scale_min_roe", 0.12))
    scale_max_owner_cv = float(policy.get("anchor_scale_max_owner_earnings_cv", 0.35))
    min_moat_proxy_score = float(policy.get("anchor_min_moat_proxy_score", 0.0))
    require_moat_proxy = bool(policy.get("anchor_require_moat_proxy", False))
    def numeric(column: str) -> pd.Series:
        values = out[column] if column in out else pd.Series(np.nan, index=out.index)
        return pd.to_numeric(values, errors="coerce")

    dividend = numeric("dv_ratio")
    owner_yield = numeric("owner_earnings_yield")
    owner_earnings = numeric("normalized_owner_earnings")
    net_cash = numeric("net_cash")
    pe = numeric("pe_ttm")
    owner_cv = numeric("owner_earnings_cv")
    normalized_roe = numeric("normalized_roe")
    revenue_cagr = numeric("revenue_cagr")
    gross_margin = numeric("normalized_gross_margin")
    gross_margin_cv = numeric("gross_margin_cv")
    gross_margin_delta = numeric("latest_gross_margin_delta")
    fcf_conversion = numeric("normalized_fcf_conversion")
    fcf_conversion = fcf_conversion.where(
        fcf_conversion.notna(), numeric("normalized_fcf") / owner_earnings.where(owner_earnings.gt(0))
    )
    subindustry_rank = numeric("subindustry_market_cap_rank")
    out["dividend_payout_proxy"] = (dividend / 100.0) / owner_yield.where(owner_yield.gt(0))
    out["economic_factor"] = assign_anchor_economic_factors(out)
    out["net_debt_to_owner_earnings"] = (-net_cash).clip(lower=0) / owner_earnings.where(owner_earnings.gt(0))
    dividend_pass = dividend.ge(min_dividend)
    owner_yield_pass = owner_yield.ge(min_owner_yield)
    cash_pass = numeric("normalized_owner_earnings").gt(0) & numeric("normalized_fcf").gt(0)
    if "anchor_min_financial_years" in policy:
        cash_pass &= numeric("financial_years").ge(float(policy["anchor_min_financial_years"]))
    if "anchor_min_positive_owner_years" in policy:
        cash_pass &= numeric("owner_earnings_positive_years").ge(float(policy["anchor_min_positive_owner_years"]))
    if "anchor_min_positive_fcf_years" in policy:
        cash_pass &= numeric("fcf_positive_years").ge(float(policy["anchor_min_positive_fcf_years"]))
    stability_pass = owner_cv.le(max_owner_cv) if np.isfinite(max_owner_cv) else pd.Series(True, index=out.index)
    quality_pass = normalized_roe.ge(min_roe) if min_roe > 0 else pd.Series(True, index=out.index)
    leverage_pass = out["net_debt_to_owner_earnings"].le(max_debt_ratio)
    valuation_pass = pe.gt(0) & pe.le(max_pe)
    revenue_pass = revenue_cagr.ge(min_revenue_cagr) if np.isfinite(min_revenue_cagr) else pd.Series(True, index=out.index)
    margin_stability_pass = gross_margin_cv.le(max_gross_margin_cv) if np.isfinite(max_gross_margin_cv) else pd.Series(True, index=out.index)
    margin_erosion_pass = gross_margin_delta.ge(min_gross_margin_delta) if np.isfinite(min_gross_margin_delta) else pd.Series(True, index=out.index)
    conversion_pass = fcf_conversion.ge(min_fcf_conversion) if np.isfinite(min_fcf_conversion) else pd.Series(True, index=out.index)
    payout_pass = out["dividend_payout_proxy"].le(max_payout_proxy) if np.isfinite(max_payout_proxy) else pd.Series(True, index=out.index)
    position_pass = subindustry_rank.le(max_subindustry_rank) if np.isfinite(max_subindustry_rank) else pd.Series(True, index=out.index)
    brand_pricing_power = (
        position_pass & gross_margin.ge(brand_gross_margin) & gross_margin_cv.le(max_gross_margin_cv)
        & normalized_roe.ge(brand_roe) & revenue_pass & margin_erosion_pass
    )
    scale_cost_leader = (
        position_pass & normalized_roe.ge(scale_roe) & owner_cv.le(scale_max_owner_cv)
        & conversion_pass & revenue_pass & margin_stability_pass & margin_erosion_pass
    )
    out["moat_proxy_type"] = np.select(
        [brand_pricing_power, scale_cost_leader, position_pass],
        ["BRAND_PRICING_POWER_PROXY", "SCALE_COST_LEADER_PROXY", "POSITION_ONLY_REVIEW"],
        default="NO_POSITION_EVIDENCE",
    )
    position_score = (1.0 / subindustry_rank.clip(lower=1)).fillna(0)
    pricing_score = ((gross_margin.clip(0.15, 0.60) - 0.15) / 0.45).fillna(0)
    revenue_score = ((revenue_cagr.clip(-0.03, 0.10) + 0.03) / 0.13).fillna(0)
    moat_roe_score = ((normalized_roe.clip(0.08, 0.25) - 0.08) / 0.17).fillna(0)
    conversion_score = ((fcf_conversion.clip(0.50, 1.00) - 0.50) / 0.50).fillna(0)
    out["moat_proxy_score"] = 100 * (
        0.30 * position_score + 0.25 * pricing_score + 0.15 * revenue_score
        + 0.15 * moat_roe_score + 0.15 * conversion_score
    )
    moat_pass = (brand_pricing_power | scale_cost_leader) & out["moat_proxy_score"].ge(min_moat_proxy_score)
    approval_pass = pd.Series(True, index=out.index) if auto_mode else out["moat_approved"]
    if require_moat_proxy:
        approval_pass &= moat_pass
    full_pass = (
        approval_pass & dividend_pass & owner_yield_pass & cash_pass & stability_pass
        & quality_pass & leverage_pass & valuation_pass & revenue_pass & margin_stability_pass
        & margin_erosion_pass & conversion_pass & payout_pass
    )
    out["defensive_status"] = np.where(
        full_pass,
        "DEFENSIVE_ELIGIBLE", "WATCH",
    )
    stability_score = (1 - owner_cv.clip(0, max_owner_cv) / max_owner_cv).fillna(0) if np.isfinite(max_owner_cv) else 1.0
    roe_score = ((normalized_roe.clip(min_roe, 0.30) - min_roe) / max(0.30 - min_roe, 1e-9)).fillna(0)
    out["financial_anchor_score"] = 100 * (
        0.20 * ((owner_yield.clip(min_owner_yield, 0.15) - min_owner_yield) / (0.15 - min_owner_yield))
        + 0.10 * ((dividend.clip(min_dividend, 8.0) - min_dividend) / (8.0 - min_dividend))
        + 0.10 * (1 - pe.clip(0, max_pe) / max_pe)
        + 0.20 * stability_score
        + 0.25 * roe_score
        + 0.05 * cash_pass.astype(float)
        + 0.10 * (1 - out["net_debt_to_owner_earnings"].clip(0, max_debt_ratio) / max_debt_ratio)
    )
    out["anchor_score"] = 0.65 * out["financial_anchor_score"] + 0.35 * out["moat_proxy_score"]
    out["first_failed_anchor_gate"] = np.select(
        [~approval_pass, ~dividend_pass, ~owner_yield_pass, ~cash_pass, ~stability_pass,
         ~quality_pass, ~leverage_pass, ~valuation_pass, ~revenue_pass,
         ~margin_stability_pass, ~margin_erosion_pass, ~conversion_pass, ~payout_pass],
        ["MOAT_PROXY_FAIL", "DIVIDEND_FAIL", "OWNER_YIELD_FAIL", "CASH_EARNINGS_FAIL",
         "OWNER_STABILITY_FAIL", "ROE_FAIL", "LEVERAGE_FAIL", "VALUATION_FAIL",
         "REVENUE_RESILIENCE_FAIL", "MARGIN_STABILITY_FAIL", "MARGIN_EROSION_FAIL",
         "FCF_CONVERSION_FAIL", "DIVIDEND_COVERAGE_FAIL"],
        default="PASS",
    )
    out["reason"] = np.where(
        out["defensive_status"].eq("DEFENSIVE_ELIGIBLE"),
        "industry-position + pricing/scale moat proxy and financial quality gates passed",
        "failed: " + out["first_failed_anchor_gate"].astype(str) if auto_mode else "requires moat evidence and financial gates",
    )
    return out.sort_values(["defensive_status", "anchor_score"], ascending=[True, False], na_position="last")


def _anchor_weights(eligible: pd.DataFrame, policy: dict) -> pd.Series:
    """Choose factor-diversified anchors, then water-fill security and group caps."""
    if eligible.empty:
        return pd.Series(dtype=float)
    target = float(policy["anchor_target"])
    max_names = int(policy.get("anchor_max_names", 6))
    stock_cap = float(policy.get("anchor_max_weight", target))
    industry_cap = float(policy.get("anchor_industry_cap", target))
    factor_cap = float(policy.get("anchor_economic_factor_cap", target))
    if "anchor_score" not in eligible:
        eligible = eligible.assign(anchor_score=0.0)
    ranked = eligible.sort_values(["anchor_score", "ts_code"], ascending=[False, True]).copy()
    if "economic_factor" not in ranked:
        ranked["economic_factor"] = assign_anchor_economic_factors(ranked)
    ranked["economic_factor"] = ranked["economic_factor"].fillna("OTHER")
    # Take the strongest company from each independent economic factor first.
    # This prevents six individually good companies from becoming one macro bet.
    representatives = ranked.groupby("economic_factor", sort=False, group_keys=False).head(1).head(max_names)
    selected_indices = list(representatives.index)
    for idx in ranked.index:
        if len(selected_indices) >= max_names:
            break
        if idx not in selected_indices:
            selected_indices.append(idx)
    selected = ranked.loc[selected_indices].copy()
    if "l1_name" not in selected:
        selected["l1_name"] = selected["ts_code"]
    selected["l1_name"] = selected["l1_name"].fillna(selected["ts_code"])
    weights = pd.Series(min(target / len(selected), stock_cap), index=selected.index, dtype=float)
    for _, idx in selected.groupby("l1_name").groups.items():
        if weights.loc[idx].sum() > industry_cap:
            weights.loc[idx] *= industry_cap / weights.loc[idx].sum()
    for _, idx in selected.groupby("economic_factor").groups.items():
        if weights.loc[idx].sum() > factor_cap:
            weights.loc[idx] *= factor_cap / weights.loc[idx].sum()
    for _ in range(20):
        remaining = target - float(weights.sum())
        if remaining <= 1e-10:
            break
        industry_used = selected.assign(_w=weights).groupby("l1_name")["_w"].sum()
        factor_used = selected.assign(_w=weights).groupby("economic_factor")["_w"].sum()
        room = pd.Series(0.0, index=selected.index)
        for idx, row in selected.iterrows():
            room.loc[idx] = max(min(
                stock_cap - weights.loc[idx],
                industry_cap - industry_used.loc[row["l1_name"]],
                factor_cap - factor_used.loc[row["economic_factor"]],
            ), 0.0)
        open_idx = room[room.gt(1e-12)].index
        if open_idx.empty:
            break
        step = min(remaining / len(open_idx), float(room.loc[open_idx].min()))
        weights.loc[open_idx] += step
    return weights


def classify_future_states(
    future: pd.DataFrame,
    milestones: pd.DataFrame,
    evidence_readiness: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Classify forward theses without using backtest performance as a gate."""
    required = {"ts_code", "policy_status", "future_thesis_score", "valuation_gate", "financial_check",
                "dcf_margin_of_safety", "timing_status"}
    missing = required - set(future.columns)
    if missing:
        raise ValueError(f"future candidates missing columns: {sorted(missing)}")
    ledger = milestones.copy()
    if "ts_code" not in ledger:
        ledger = pd.DataFrame(columns=["ts_code", *MILESTONE_COLUMNS, "invalidation_status"])
    for col in MILESTONE_COLUMNS:
        if col not in ledger:
            ledger[col] = "UNVERIFIED"
    if "invalidation_status" not in ledger:
        ledger["invalidation_status"] = "NONE"
    out = future.merge(ledger, on="ts_code", how="left", suffixes=("", "_milestone"))
    evidence_gate_enabled = evidence_readiness is not None
    if evidence_gate_enabled:
        if "ts_code" not in evidence_readiness or "evidence_status" not in evidence_readiness:
            raise ValueError("evidence readiness requires ts_code and evidence_status")
        evidence_fields = [
            column for column in [
                "ts_code", "evidence_status", "seed_evidence_ready", "promotion_evidence_ready",
                "supported_evidence_types", "missing_evidence_types", "active_evidence_count",
                "caution_evidence_count", "registry_next_review_date",
            ] if column in evidence_readiness
        ]
        out = out.merge(evidence_readiness[evidence_fields], on="ts_code", how="left")
        out["evidence_status"] = out["evidence_status"].fillna("NOT_REGISTERED")
        out["seed_evidence_ready"] = out["seed_evidence_ready"].fillna(False).astype(bool)
        out["promotion_evidence_ready"] = out.get(
            "promotion_evidence_ready", pd.Series(False, index=out.index)
        ).fillna(False).astype(bool)
    else:
        out["evidence_status"] = "LEGACY_NOT_ENFORCED"
        out["seed_evidence_ready"] = True
        out["promotion_evidence_ready"] = True
    for col in MILESTONE_COLUMNS:
        out[col] = out[col].fillna("UNVERIFIED").astype(str).str.upper()
    out["invalidation_status"] = out["invalidation_status"].fillna("NONE").astype(str).str.upper()
    milestones_pass = out[MILESTONE_COLUMNS].eq("VERIFIED").all(axis=1)
    out["verified_milestone_count"] = out[MILESTONE_COLUMNS].eq("VERIFIED").sum(axis=1)
    invalidated = out["invalidation_status"].eq("TRIGGERED")
    policy_pass = out["policy_status"].eq("POLICY_ELIGIBLE")
    thesis_pass = pd.to_numeric(out["future_thesis_score"], errors="coerce").ge(72)
    value_pass = (out["valuation_gate"].isin({"REASONABLE", "FAIR_TO_RICH"})
                  & pd.to_numeric(out["dcf_margin_of_safety"], errors="coerce").ge(0))
    cash_pass = out["financial_check"].eq("PASS_SURVIVAL")
    bottom = out["timing_status"].eq("BOTTOM_HOLD_NO_ADD")
    trend = out["timing_status"].eq("BOTTOM_VOLUME_CONFIRMATION")
    evidence_pass = out["seed_evidence_ready"]
    promotion_evidence_pass = out["promotion_evidence_ready"]
    build_ready = out["verified_milestone_count"].ge(2)
    out["barbell_state"] = np.select(
        [invalidated,
         policy_pass & thesis_pass & value_pass & cash_pass & promotion_evidence_pass & milestones_pass & trend,
         policy_pass & thesis_pass & value_pass & cash_pass & evidence_pass & build_ready & (bottom | trend),
         policy_pass & thesis_pass & value_pass & cash_pass & evidence_pass & (bottom | trend)],
        ["INVALIDATED", "PROMOTED_CORE", "CONFIRMED_BUILD", "OPTION_SEED"],
        default="RESEARCH_ONLY",
    )
    evidence_failed = evidence_gate_enabled & ~evidence_pass
    out["state_reason"] = np.select(
        [invalidated,
         out["barbell_state"].eq("PROMOTED_CORE"),
         out["barbell_state"].eq("CONFIRMED_BUILD"),
         out["barbell_state"].eq("OPTION_SEED"),
         evidence_failed],
        ["invalidation trigger recorded",
         "national policy + thesis + value + cash earnings + seed evidence + 3 milestones + bottom-volume trend confirmed",
         "national policy + thesis + value + cash earnings + seed evidence + at least 2 milestones confirmed; staged build/reduction weight",
         "national policy + thesis + value + cash earnings + auditable seed evidence + bottom/trend position; promotion gates not complete",
         "seed evidence gate failed: " + out["evidence_status"].astype(str)],
        default="one or more policy, thesis, value, cash-earnings, milestone or timing gates failed",
    )
    return out


def build_barbell_weights(
    anchors: pd.DataFrame,
    future_states: pd.DataFrame,
    policy: dict,
) -> tuple[pd.DataFrame, dict]:
    """Allocate anchors, small option seeds and promoted cores; leave the rest in cash."""
    anchor_target = float(policy["anchor_target"])
    cash_floor = float(policy["cash_floor"])
    seed_weight = float(policy["option_seed_weight"])
    future_cap = float(policy["future_total_cap"])
    seed_target_min = float(policy.get("option_seed_target_min", 0.0))
    seed_cap = float(policy.get("option_seed_total_cap", future_cap))
    build_weight = float(policy.get("confirmed_build_weight", 0.05))
    core_weight = float(policy["promoted_core_weight"])
    theme_cap = float(policy["single_theme_cap"])
    if seed_target_min > seed_cap + 1e-9:
        raise ValueError("option_seed_target_min cannot exceed option_seed_total_cap")
    if anchor_target + future_cap + cash_floor > 1.0 + 1e-9:
        raise ValueError("anchor_target + future_total_cap + cash_floor cannot exceed 1")

    rows: list[dict] = []
    eligible_anchors = anchors[anchors["defensive_status"].eq("DEFENSIVE_ELIGIBLE")].copy()
    anchor_weights = _anchor_weights(eligible_anchors, policy)
    eligible_anchors = eligible_anchors.loc[anchor_weights.index].copy()
    if not eligible_anchors.empty:
        for idx, row in eligible_anchors.iterrows():
            rows.append({"ts_code": row["ts_code"], "name": row.get("name"), "theme": "稳定现金流",
                         "l1_name": row.get("l1_name"),
                         "economic_factor": row.get("economic_factor"),
                         "moat_proxy_type": row.get("moat_proxy_type"),
                         "moat_proxy_score": row.get("moat_proxy_score"),
                         "moat_evidence_status": "PROXY_REQUIRES_PRIMARY_EVIDENCE",
                         "allocation_bucket": "ANCHOR", "strategy_state": "ANCHOR",
                         "target_weight": float(anchor_weights.loc[idx]), "reason": row.get("reason", "automatic anchor")})

    # A security can serve one sleeve only. Once approved as a stable anchor it
    # cannot simultaneously consume the future-industry risk budget.
    anchor_codes = set(eligible_anchors["ts_code"].astype(str)) if "ts_code" in eligible_anchors else set()
    if future_states.empty or "ts_code" not in future_states:
        candidates = pd.DataFrame(columns=[*future_states.columns, "ts_code"])
    else:
        candidates = future_states[
            future_states["barbell_state"].isin(["PROMOTED_CORE", "CONFIRMED_BUILD", "OPTION_SEED"])
            & ~future_states["ts_code"].astype(str).isin(anchor_codes)
        ].copy()
    for column in ["barbell_state", "future_thesis_score"]:
        if column not in candidates:
            candidates[column] = pd.Series(dtype=object if column == "barbell_state" else float)
    candidates["_state_order"] = candidates["barbell_state"].map(
        {"PROMOTED_CORE": 0, "CONFIRMED_BUILD": 1, "OPTION_SEED": 2}
    )
    candidates = candidates.sort_values(["_state_order", "future_thesis_score"], ascending=[True, False])
    future_used = 0.0
    seed_used = 0.0
    theme_used: dict[str, float] = {}
    for _, row in candidates.iterrows():
        requested = {
            "PROMOTED_CORE": core_weight,
            "CONFIRMED_BUILD": build_weight,
            "OPTION_SEED": seed_weight,
        }[row["barbell_state"]]
        theme = str(row.get("theme", "未分类"))
        allowed = min(requested, future_cap - future_used, theme_cap - theme_used.get(theme, 0.0))
        if row["barbell_state"] == "OPTION_SEED":
            allowed = min(allowed, seed_cap - seed_used)
        if allowed <= 1e-12:
            continue
        rows.append({"ts_code": row["ts_code"], "name": row.get("name"), "theme": theme,
                     "l1_name": row.get("l1_name"),
                     "economic_factor": None, "moat_proxy_type": None,
                     "moat_proxy_score": np.nan, "moat_evidence_status": None,
                     "allocation_bucket": "FUTURE", "strategy_state": row["barbell_state"],
                     "target_weight": allowed, "reason": row["state_reason"]})
        future_used += allowed
        if row["barbell_state"] == "OPTION_SEED":
            seed_used += allowed
        theme_used[theme] = theme_used.get(theme, 0.0) + allowed

    portfolio = pd.DataFrame(rows, columns=[
        "ts_code", "name", "theme", "l1_name", "economic_factor", "moat_proxy_type",
        "moat_proxy_score", "moat_evidence_status", "allocation_bucket", "strategy_state",
        "target_weight", "reason",
    ])
    anchor_used = float(portfolio.loc[portfolio["allocation_bucket"].eq("ANCHOR"), "target_weight"].sum()) if not portfolio.empty else 0.0
    cash_weight = max(1.0 - anchor_used - future_used, 0.0)
    seed_target_status = "WITHIN_TARGET" if seed_used + 1e-12 >= seed_target_min else "BELOW_TARGET_EVIDENCE_LIMITED"
    confirmed_build_used = float(portfolio.loc[
        portfolio["strategy_state"].eq("CONFIRMED_BUILD"), "target_weight"
    ].sum()) if not portfolio.empty else 0.0
    promoted_core_used = float(portfolio.loc[
        portfolio["strategy_state"].eq("PROMOTED_CORE"), "target_weight"
    ].sum()) if not portfolio.empty else 0.0
    summary = {"anchor_weight": anchor_used, "future_weight": future_used, "option_seed_weight": seed_used,
               "confirmed_build_weight": confirmed_build_used, "promoted_core_weight": promoted_core_used,
               "option_seed_target_min": seed_target_min, "option_seed_total_cap": seed_cap,
               "option_seed_target_status": seed_target_status, "cash_weight": cash_weight,
               "anchor_unallocated": anchor_target - anchor_used,
               "future_capacity_remaining": future_cap - future_used}
    return portfolio, summary
