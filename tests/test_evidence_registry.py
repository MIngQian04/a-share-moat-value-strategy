import pandas as pd

from selection.evidence_registry import build_evidence_readiness


def registry() -> pd.DataFrame:
    return pd.DataFrame([{
        "ts_code": "A",
        "demand_hypothesis": "demand",
        "profit_pool_hypothesis": "profit",
        "company_exposure_hypothesis": "company",
        "invalidation_rule": "two review periods below target",
        "next_review_date": "2026-10-31",
    }])


def evidence(direction: str = "SUPPORTS") -> pd.DataFrame:
    return pd.DataFrame([{
        "evidence_id": f"E-{kind}",
        "ts_code": "A",
        "evidence_type": kind,
        "claim": f"{kind} claim",
        "evidence_date": "2026-06-30",
        "published_date": "2026-07-10",
        "source_type": "COMPANY_FILING",
        "source_url": f"https://example.com/{kind}",
        "direction": direction,
        "next_review_date": "2026-10-31",
    } for kind in ["DEMAND", "PROFIT_POOL", "COMPANY_EXPOSURE"]])


def test_seed_ready_requires_all_three_current_primary_evidence_types():
    result = build_evidence_readiness(registry(), evidence(), "2026-07-16").iloc[0]
    assert result["evidence_status"] == "SEED_READY"
    assert bool(result["seed_evidence_ready"])


def test_missing_evidence_type_blocks_seed():
    result = build_evidence_readiness(registry(), evidence().iloc[:2], "2026-07-16").iloc[0]
    assert result["evidence_status"] == "EVIDENCE_INCOMPLETE"
    assert "COMPANY_EXPOSURE" in result["missing_evidence_types"]


def test_overdue_thesis_review_blocks_seed():
    card = registry()
    card["next_review_date"] = "2026-07-01"
    result = build_evidence_readiness(card, evidence(), "2026-07-16").iloc[0]
    assert result["evidence_status"] == "THESIS_REVIEW_OVERDUE"


def test_current_contradictory_primary_evidence_blocks_seed():
    ledger = pd.concat([evidence(), evidence("CONTRADICTS").iloc[:1]], ignore_index=True)
    result = build_evidence_readiness(registry(), ledger, "2026-07-16").iloc[0]
    assert result["evidence_status"] == "CONTRADICTED"


def test_caution_is_retained_but_does_not_block_a_supported_seed():
    caution = evidence().iloc[:1].copy()
    caution["evidence_id"] = "E-CAUTION"
    caution["direction"] = "CAUTION"
    ledger = pd.concat([evidence(), caution], ignore_index=True)
    result = build_evidence_readiness(registry(), ledger, "2026-07-16").iloc[0]
    assert result["evidence_status"] == "SEED_READY_WITH_CAUTION"
    assert bool(result["seed_evidence_ready"])
    assert not bool(result["promotion_evidence_ready"])
    assert result["active_evidence_count"] == 4
