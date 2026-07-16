from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd


ALERT_COLUMNS = [
    "alert_id", "ts_code", "name", "alert_date", "alert_source", "alert_level",
    "category", "trigger", "title", "source_url", "review_status", "suggested_action",
]

ANNOUNCEMENT_RULES = [
    ("HIGH", "REGULATORY_OR_SURVIVAL", ("立案调查", "行政处罚", "重大违法", "终止上市", "被申请破产", "债务逾期")),
    ("HIGH", "MOAT_OR_EARNINGS_RISK", ("产品召回", "核心技术人员离职", "大额减值", "业绩预亏", "重大诉讼")),
    ("MEDIUM", "GOVERNANCE_CHANGE", ("实际控制人变更", "董事长辞职", "总经理辞职", "问询函", "监管函")),
    ("MEDIUM", "BUSINESS_CHANGE", ("业绩预告", "业绩快报", "诉讼", "仲裁", "重大合同", "中标", "关联交易", "收购", "出售资产", "担保", "减持", "质押")),
]


def _alert_id(*parts: object) -> str:
    raw = "|".join(str(part) for part in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _alerts(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=ALERT_COLUMNS)
    return pd.DataFrame(rows, columns=ALERT_COLUMNS).drop_duplicates("alert_id", keep="last")


def build_announcement_alerts(announcements: pd.DataFrame, as_of: str) -> pd.DataFrame:
    rows: list[dict] = []
    cutoff = pd.Timestamp(as_of).normalize()
    for announcement in announcements.to_dict("records"):
        date = pd.to_datetime(announcement.get("ann_date"), errors="coerce")
        if pd.isna(date) or date.normalize() > cutoff:
            continue
        title = str(announcement.get("title", "")).strip()
        matched = None
        for level, category, keywords in ANNOUNCEMENT_RULES:
            trigger = next((keyword for keyword in keywords if keyword in title), None)
            if trigger:
                matched = (level, category, trigger)
                break
        if not matched:
            continue
        level, category, trigger = matched
        code = str(announcement.get("ts_code", ""))
        date_text = date.strftime("%Y-%m-%d")
        rows.append({
            "alert_id": _alert_id("ANNOUNCEMENT", code, date_text, title, announcement.get("url", "")),
            "ts_code": code,
            "name": str(announcement.get("name", "")),
            "alert_date": date_text,
            "alert_source": "COMPANY_ANNOUNCEMENT",
            "alert_level": level,
            "category": category,
            "trigger": trigger,
            "title": title,
            "source_url": str(announcement.get("url", "")),
            "review_status": "PENDING_REVIEW",
            "suggested_action": "暂停加仓，打开公告原文核查其是否改变护城河机制",
        })
    return _alerts(rows)


def _statement(path: Path, as_of: pd.Timestamp) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    frame = pd.read_parquet(path).copy()
    for column in ["ann_date", "end_date"]:
        frame[column] = pd.to_datetime(frame.get(column), errors="coerce")
    frame = frame[frame["ann_date"].le(as_of) & frame["end_date"].notna()]
    return frame.sort_values(["end_date", "ann_date"], ascending=[False, False]).drop_duplicates("end_date")


def _yoy(current: object, previous: object) -> float | None:
    current_value = pd.to_numeric(current, errors="coerce")
    previous_value = pd.to_numeric(previous, errors="coerce")
    if pd.isna(current_value) or pd.isna(previous_value) or float(previous_value) <= 0:
        return None
    return float(current_value / previous_value - 1)


def build_financial_alerts(
    holdings: pd.DataFrame,
    financial_root: Path,
    as_of: str,
) -> tuple[pd.DataFrame, dict]:
    """Flag material same-period deterioration; never turn it into a moat verdict."""
    rows: list[dict] = []
    checked = 0
    missing: list[str] = []
    as_of_date = pd.Timestamp(as_of).normalize()
    rules = [
        ("revenue", "收入同比", -0.10, "OPERATING_DETERIORATION"),
        ("n_income_attr_p", "归母净利润同比", -0.20, "EARNINGS_DETERIORATION"),
        ("n_cashflow_act", "经营现金流同比", -0.25, "CASHFLOW_DETERIORATION"),
    ]
    for holding in holdings.to_dict("records"):
        code = str(holding["ts_code"])
        stem = code.replace(".", "_")
        income = _statement(financial_root / "income" / f"{stem}.parquet", as_of_date)
        cashflow = _statement(financial_root / "cashflow" / f"{stem}.parquet", as_of_date)
        if income.empty and cashflow.empty:
            missing.append(code)
            continue
        latest_end = max(
            [frame.iloc[0]["end_date"] for frame in [income, cashflow] if not frame.empty]
        )
        prior_end = latest_end - pd.DateOffset(years=1)
        current_income = income[income["end_date"].eq(latest_end)]
        prior_income = income[income["end_date"].eq(prior_end)]
        current_cash = cashflow[cashflow["end_date"].eq(latest_end)]
        prior_cash = cashflow[cashflow["end_date"].eq(prior_end)]
        if current_income.empty or prior_income.empty:
            missing.append(code)
            continue
        checked += 1
        report_date = max(
            [frame.iloc[0]["ann_date"] for frame in [current_income, current_cash] if not frame.empty]
        )
        for field, label, threshold, category in rules:
            source_current = current_cash if field == "n_cashflow_act" else current_income
            source_prior = prior_cash if field == "n_cashflow_act" else prior_income
            if source_current.empty or source_prior.empty or field not in source_current or field not in source_prior:
                continue
            change = _yoy(source_current.iloc[0][field], source_prior.iloc[0][field])
            if change is None or change > threshold:
                continue
            title = f"{latest_end.strftime('%Y-%m-%d')} {label}{change:+.1%}，达到复核阈值"
            rows.append({
                "alert_id": _alert_id("FINANCIAL", code, latest_end.date(), field),
                "ts_code": code,
                "name": str(holding.get("name", "")),
                "alert_date": report_date.strftime("%Y-%m-%d"),
                "alert_source": "QUARTERLY_FINANCIAL",
                "alert_level": "HIGH" if change <= threshold * 2 else "MEDIUM",
                "category": category,
                "trigger": label,
                "title": title,
                "source_url": "",
                "review_status": "PENDING_REVIEW",
                "suggested_action": "暂停加仓，核查同比基数、一次性因素及护城河经营指标",
            })
    return _alerts(rows), {"codes_checked": checked, "missing_codes": sorted(set(missing))}


def build_review_due_alerts(registry: pd.DataFrame, as_of: str) -> pd.DataFrame:
    rows: list[dict] = []
    today = pd.Timestamp(as_of).normalize()
    for card in registry.to_dict("records"):
        due = pd.to_datetime(card.get("next_review_date"), errors="coerce")
        if pd.isna(due) or due.normalize() >= today:
            continue
        code = str(card.get("ts_code", ""))
        title = f"护城河定期复核已于 {due.strftime('%Y-%m-%d')} 到期"
        rows.append({
            "alert_id": _alert_id("REVIEW_DUE", code, due.date()),
            "ts_code": code, "name": str(card.get("name", "")),
            "alert_date": today.strftime("%Y-%m-%d"), "alert_source": "REVIEW_CALENDAR",
            "alert_level": "MEDIUM", "category": "REVIEW_DUE", "trigger": "复核到期",
            "title": title, "source_url": "", "review_status": "PENDING_REVIEW",
            "suggested_action": "暂停加仓，完成年度或关键节点护城河复核",
        })
    return _alerts(rows)
