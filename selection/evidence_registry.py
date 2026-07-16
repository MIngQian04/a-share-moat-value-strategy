from __future__ import annotations

from collections.abc import Iterable

import pandas as pd


REQUIRED_EVIDENCE_TYPES = ("DEMAND", "PROFIT_POOL", "COMPANY_EXPOSURE")
TRUSTED_SOURCE_TYPES = ("GOVERNMENT_PRIMARY", "COMPANY_FILING", "INDUSTRY_PRIMARY")
REGISTRY_FIELDS = (
    "demand_hypothesis",
    "profit_pool_hypothesis",
    "company_exposure_hypothesis",
    "invalidation_rule",
    "next_review_date",
)
EVIDENCE_FIELDS = (
    "evidence_id",
    "ts_code",
    "evidence_type",
    "claim",
    "evidence_date",
    "published_date",
    "source_type",
    "source_url",
    "direction",
    "next_review_date",
)


def _nonempty(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series(False, index=frame.index)
    return frame[column].fillna("").astype(str).str.strip().ne("")


def _ensure_columns(frame: pd.DataFrame, columns: Iterable[str], label: str) -> None:
    missing = set(columns) - set(frame.columns)
    if missing:
        raise ValueError(f"{label} missing columns: {sorted(missing)}")


def build_evidence_readiness(
    registry: pd.DataFrame,
    evidence: pd.DataFrame,
    as_of: str | pd.Timestamp,
    required_types: Iterable[str] = REQUIRED_EVIDENCE_TYPES,
    trusted_source_types: Iterable[str] = TRUSTED_SOURCE_TYPES,
) -> pd.DataFrame:
    """Summarize whether a forward thesis has auditable evidence for a seed position.

    The ledger is append-only. A seed is ready only when the thesis card is
    complete and current, and each required evidence category has at least one
    current supporting primary source. Any current contradictory primary source
    blocks the seed until it is reviewed.
    """
    _ensure_columns(registry, ("ts_code", *REGISTRY_FIELDS), "thesis registry")
    _ensure_columns(evidence, EVIDENCE_FIELDS, "evidence ledger")
    as_of_date = pd.Timestamp(as_of).normalize()
    required = tuple(str(value).upper() for value in required_types)
    trusted = {str(value).upper() for value in trusted_source_types}

    cards = registry.copy()
    cards["ts_code"] = cards["ts_code"].astype(str)
    cards["registry_complete"] = pd.concat(
        [_nonempty(cards, column) for column in REGISTRY_FIELDS], axis=1
    ).all(axis=1)
    cards["registry_review_date"] = pd.to_datetime(cards["next_review_date"], errors="coerce")
    cards["registry_current"] = cards["registry_review_date"].ge(as_of_date)

    ledger = evidence.copy()
    ledger["ts_code"] = ledger["ts_code"].astype(str)
    ledger["evidence_type"] = ledger["evidence_type"].fillna("").astype(str).str.upper()
    ledger["source_type"] = ledger["source_type"].fillna("").astype(str).str.upper()
    ledger["direction"] = ledger["direction"].fillna("").astype(str).str.upper()
    for column in ["evidence_date", "published_date", "next_review_date"]:
        ledger[column] = pd.to_datetime(ledger[column], errors="coerce")
    ledger["dated"] = (
        ledger["evidence_date"].notna()
        & ledger["published_date"].notna()
        & ledger["evidence_date"].le(as_of_date)
        & ledger["published_date"].le(as_of_date)
    )
    ledger["current"] = ledger["next_review_date"].ge(as_of_date)
    ledger["traceable"] = _nonempty(ledger, "source_url") & _nonempty(ledger, "claim")
    ledger["trusted"] = ledger["source_type"].isin(trusted)
    active = ledger[ledger["dated"] & ledger["current"] & ledger["traceable"] & ledger["trusted"]].copy()

    rows: list[dict] = []
    for _, card in cards.drop_duplicates("ts_code", keep="last").iterrows():
        code = str(card["ts_code"])
        company_evidence = active[active["ts_code"].eq(code)]
        supported = {
            evidence_type
            for evidence_type in required
            if (
                company_evidence["evidence_type"].eq(evidence_type)
                & company_evidence["direction"].eq("SUPPORTS")
            ).any()
        }
        contradicted = company_evidence["direction"].eq("CONTRADICTS").any()
        caution_count = int(company_evidence["direction"].eq("CAUTION").sum())
        missing_types = [value for value in required if value not in supported]
        if not bool(card["registry_complete"]):
            status = "THESIS_INCOMPLETE"
        elif not bool(card["registry_current"]):
            status = "THESIS_REVIEW_OVERDUE"
        elif contradicted:
            status = "CONTRADICTED"
        elif missing_types:
            status = "EVIDENCE_INCOMPLETE"
        elif caution_count:
            status = "SEED_READY_WITH_CAUTION"
        else:
            status = "SEED_READY"
        rows.append(
            {
                "ts_code": code,
                "evidence_status": status,
                "seed_evidence_ready": status in {"SEED_READY", "SEED_READY_WITH_CAUTION"},
                "promotion_evidence_ready": status == "SEED_READY",
                "supported_evidence_types": "|".join(sorted(supported)),
                "missing_evidence_types": "|".join(missing_types),
                "active_evidence_count": int(len(company_evidence)),
                "caution_evidence_count": caution_count,
                "registry_next_review_date": card.get("next_review_date"),
            }
        )
    return pd.DataFrame(rows)
