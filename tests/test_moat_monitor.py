import pandas as pd

from selection.moat_monitor import build_moat_monitor


def registry() -> pd.DataFrame:
    return pd.DataFrame([{
        "ts_code": "A", "name": "A", "moat_type": "brand", "moat_thesis": "mindshare",
        "replication_barrier": "time", "monitoring_signals": "price|share",
        "invalidation_signals": "discount", "last_review_date": "2026-07-01",
        "next_review_date": "2026-10-31", "action_if_intact": "hold",
        "action_if_weakened": "reduce",
    }])


def evidence(direction="SUPPORTS") -> pd.DataFrame:
    return pd.DataFrame([{
        "evidence_id": "E1", "ts_code": "A", "claim": "primary evidence",
        "evidence_date": "2026-06-30", "published_date": "2026-07-10",
        "source_type": "COMPANY_FILING", "source_url": "https://example.com/a",
        "direction": direction, "next_review_date": "2026-10-31",
    }])


def test_draft_is_not_misrepresented_as_verified_moat():
    empty = evidence().iloc[0:0]
    result = build_moat_monitor(registry(), empty, "2026-07-16").iloc[0]
    assert result["moat_status"] == "DRAFT"
    assert "不因历史财务加仓" in result["recommended_action"]


def test_current_primary_support_marks_moat_intact():
    result = build_moat_monitor(registry(), evidence(), "2026-07-16").iloc[0]
    assert result["moat_status"] == "INTACT"
    assert result["recommended_action"] == "hold"


def test_contradiction_overrides_support_and_recommends_reduction():
    ledger = pd.concat([evidence(), evidence("CONTRADICTS")], ignore_index=True)
    ledger.loc[1, "evidence_id"] = "E2"
    result = build_moat_monitor(registry(), ledger, "2026-07-16").iloc[0]
    assert result["moat_status"] == "WEAKENED"
    assert result["recommended_action"] == "reduce"


def test_overdue_review_freezes_additions():
    card = registry()
    card["next_review_date"] = "2026-07-01"
    result = build_moat_monitor(card, evidence(), "2026-07-16").iloc[0]
    assert result["moat_status"] == "REVIEW_DUE"
    assert "暂停加仓" in result["recommended_action"]
