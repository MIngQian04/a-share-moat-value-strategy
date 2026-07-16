from __future__ import annotations

import pandas as pd


REGISTRY_FIELDS = (
    "ts_code", "name", "moat_type", "moat_thesis", "replication_barrier",
    "monitoring_signals", "invalidation_signals", "last_review_date",
    "next_review_date", "action_if_intact", "action_if_weakened",
)
EVIDENCE_FIELDS = (
    "evidence_id", "ts_code", "claim", "evidence_date", "published_date",
    "source_type", "source_url", "direction", "next_review_date",
)
TRUSTED_SOURCE_TYPES = {"COMPANY_FILING", "GOVERNMENT_PRIMARY", "INDUSTRY_PRIMARY"}


def _require(frame: pd.DataFrame, fields: tuple[str, ...], label: str) -> None:
    missing = set(fields) - set(frame.columns)
    if missing:
        raise ValueError(f"{label} missing columns: {sorted(missing)}")


def build_moat_monitor(registry: pd.DataFrame, evidence: pd.DataFrame, as_of: str) -> pd.DataFrame:
    """Build a current, auditable moat judgment from thesis cards and append-only evidence."""
    _require(registry, REGISTRY_FIELDS, "moat registry")
    _require(evidence, EVIDENCE_FIELDS, "moat evidence ledger")
    today = pd.Timestamp(as_of).normalize()
    cards = registry.copy().drop_duplicates("ts_code", keep="last")
    cards["ts_code"] = cards["ts_code"].astype(str)
    cards["next_review_date"] = pd.to_datetime(cards["next_review_date"], errors="coerce")

    ledger = evidence.copy()
    ledger["ts_code"] = ledger["ts_code"].astype(str)
    ledger["source_type"] = ledger["source_type"].fillna("").astype(str).str.upper()
    ledger["direction"] = ledger["direction"].fillna("").astype(str).str.upper()
    for column in ["evidence_date", "published_date", "next_review_date"]:
        ledger[column] = pd.to_datetime(ledger[column], errors="coerce")
    active = ledger[
        ledger["evidence_date"].le(today)
        & ledger["published_date"].le(today)
        & ledger["next_review_date"].ge(today)
        & ledger["source_type"].isin(TRUSTED_SOURCE_TYPES)
        & ledger["source_url"].fillna("").astype(str).str.strip().ne("")
        & ledger["claim"].fillna("").astype(str).str.strip().ne("")
    ].copy()

    rows: list[dict] = []
    for _, card in cards.iterrows():
        code = str(card["ts_code"])
        company = active[active["ts_code"].eq(code)]
        supports = company[company["direction"].eq("SUPPORTS")]
        cautions = company[company["direction"].eq("CAUTION")]
        contradictions = company[company["direction"].eq("CONTRADICTS")]
        if pd.isna(card["next_review_date"]) or card["next_review_date"] < today:
            status = "REVIEW_DUE"
            action = "暂停加仓，先完成护城河复核"
        elif not contradictions.empty:
            status = "WEAKENED"
            action = str(card["action_if_weakened"])
        elif not cautions.empty:
            status = "WATCH"
            action = "维持或降低仓位，暂停加仓并核查风险证据"
        elif not supports.empty:
            status = "INTACT"
            action = str(card["action_if_intact"])
        else:
            status = "DRAFT"
            action = "维持现有仓位上限，完成原始证据核验前不因历史财务加仓"
        rows.append({
            **{field: card.get(field, "") for field in REGISTRY_FIELDS},
            "moat_status": status,
            "recommended_action": action,
            "supporting_evidence_count": int(len(supports)),
            "caution_evidence_count": int(len(cautions)),
            "contradictory_evidence_count": int(len(contradictions)),
            "latest_evidence_date": (
                company["evidence_date"].max().strftime("%Y-%m-%d") if not company.empty else ""
            ),
            "next_review_date": card["next_review_date"].strftime("%Y-%m-%d") if pd.notna(card["next_review_date"]) else "",
        })
    return pd.DataFrame(rows)
