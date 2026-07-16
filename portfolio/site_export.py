from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from selection.moat_monitor import build_moat_monitor


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TRADING_DAYS = 252
DIVIDEND_EVENTS_PATH = PROJECT_ROOT / "data/processed/portfolio/dividend_events.csv"
MOAT_REGISTRY_PATH = PROJECT_ROOT / "config/moat-thesis-registry.csv"
MOAT_EVIDENCE_PATH = PROJECT_ROOT / "config/moat-evidence-ledger.csv"
MOAT_ALERTS_PATH = PROJECT_ROOT / "outputs/barbell-strategy/moat_radar_alerts.csv"
MOAT_HEALTH_PATH = PROJECT_ROOT / "outputs/barbell-strategy/moat_radar_health.csv"
DIVIDEND_LEDGER_COLUMNS = [
    "event_id", "ts_code", "name", "ex_date", "pay_date", "cash_div_per_share",
    "entitlement_per_unit", "status", "paid_date", "reinvest_date",
]
NAV_DIVIDEND_COLUMNS = [
    "price_return", "cash_dividend_return", "stock_dividend_return",
    "dividend_cash_per_unit", "cumulative_dividend_cash",
    "reinvested_dividend_cash", "pending_dividend_cash", "dividend_receivable",
]


def _number(value, default=0.0):
    return default if pd.isna(value) else float(value)


def _skew_label(value: float) -> str:
    if value >= 0.5:
        return "右尾机会型"
    if value <= -0.5:
        return "左尾风险型"
    return "近对称分布"


def _kurtosis_label(value: float) -> str:
    if value >= 3:
        return "高厚尾跳跃型"
    if value >= 1:
        return "厚尾波动型"
    if value <= -0.5:
        return "平尾均衡型"
    return "常态尾部"


def _distribution_metrics(returns: pd.Series) -> dict:
    returns = pd.to_numeric(returns, errors="coerce").dropna().tail(TRADING_DAYS)
    if returns.empty:
        return {
            "skewness": 0.0,
            "excessKurtosis": 0.0,
            "skewLabel": "数据不足",
            "kurtosisLabel": "数据不足",
            "observations": 0,
        }
    skewness = _number(returns.skew())
    excess_kurtosis = _number(returns.kurt())
    return {
        "skewness": skewness,
        "excessKurtosis": excess_kurtosis,
        "skewLabel": _skew_label(skewness),
        "kurtosisLabel": _kurtosis_label(excess_kurtosis),
        "observations": int(returns.size),
    }


def _portfolio_distribution(portfolio: pd.DataFrame) -> tuple[dict[str, dict], dict, dict[str, float]]:
    """Describe trailing return distributions from adjusted closes."""
    close = pd.read_parquet(PROJECT_ROOT / "data/processed/research/close.parquet")
    codes = portfolio["ts_code"].astype(str).tolist()
    available = [code for code in codes if code in close.columns]
    prices = close[available].apply(pd.to_numeric, errors="coerce")
    returns = prices.pct_change(fill_method=None)

    stock_distribution = {code: _distribution_metrics(returns[code]) for code in available}
    latest_returns = {
        code: _number(returns[code].dropna().iloc[-1]) if not returns[code].dropna().empty else 0.0
        for code in available
    }
    for code in codes:
        stock_distribution.setdefault(code, _distribution_metrics(pd.Series(dtype=float)))
        latest_returns.setdefault(code, 0.0)

    aligned = returns[available].dropna(how="any").tail(TRADING_DAYS)
    weights = portfolio.set_index("ts_code")["target_weight"].astype(float).reindex(available).fillna(0)
    portfolio_returns = aligned.mul(weights, axis="columns").sum(axis=1)
    summary = _distribution_metrics(portfolio_returns)
    summary.update({
        "periodStart": str(aligned.index.min().date()) if not aligned.empty else "",
        "periodEnd": str(aligned.index.max().date()) if not aligned.empty else "",
        "method": "当前目标仓位的近252个共同交易日；偏度描述方向，峰度为超额峰度并描述极端波动频率",
    })
    return stock_distribution, summary, latest_returns


def _load_dividend_events() -> pd.DataFrame:
    if not DIVIDEND_EVENTS_PATH.exists():
        return pd.DataFrame(columns=["ts_code", "end_date", "ex_date", "pay_date", "cash_div", "stk_div"])
    events = pd.read_csv(DIVIDEND_EVENTS_PATH)
    for column in ["ts_code", "end_date", "ex_date", "pay_date"]:
        if column not in events:
            events[column] = ""
        events[column] = events[column].fillna("").astype(str)
    for column in ["cash_div", "stk_div"]:
        if column not in events:
            events[column] = 0.0
        events[column] = pd.to_numeric(events[column], errors="coerce").fillna(0.0)
    return events


def _prepare_dividend_ledger(path: Path, as_of: str) -> pd.DataFrame:
    ledger = pd.read_csv(path) if path.exists() else pd.DataFrame(columns=DIVIDEND_LEDGER_COLUMNS)
    for column in DIVIDEND_LEDGER_COLUMNS:
        if column not in ledger:
            ledger[column] = "" if column not in {"cash_div_per_share", "entitlement_per_unit"} else 0.0
    ledger = ledger[DIVIDEND_LEDGER_COLUMNS].copy()
    for column in ["ex_date", "pay_date", "paid_date", "reinvest_date", "status"]:
        ledger[column] = ledger[column].fillna("").astype(str)
    ledger["entitlement_per_unit"] = pd.to_numeric(ledger["entitlement_per_unit"], errors="coerce").fillna(0.0)
    paid = ledger["status"].eq("RECEIVABLE") & ledger["pay_date"].ne("") & ledger["pay_date"].le(as_of)
    ledger.loc[paid, "status"] = "PAID_PENDING"
    ledger.loc[paid, "paid_date"] = ledger.loc[paid, "pay_date"]
    reinvest = ledger["status"].eq("PAID_PENDING") & ledger["paid_date"].ne("") & ledger["paid_date"].lt(as_of)
    ledger.loc[reinvest, "status"] = "REINVESTED"
    ledger.loc[reinvest, "reinvest_date"] = as_of
    return ledger


def update_portfolio_nav_history(output_dir: Path, daily_basic: pd.DataFrame) -> None:
    """Append an idempotent close-to-close total-return NAV observation.

    Raw close returns are augmented on the ex-date by Tushare's after-tax cash
    dividend and stock-dividend ratios. Cash entitlements are tracked through
    receivable, paid-pending and next-session target-weight reinvestment states.
    """
    portfolio = pd.read_csv(output_dir / "target_portfolio.csv")
    summary = pd.read_csv(output_dir / "portfolio_summary.csv").iloc[0]
    as_of = str(summary["as_of_date"])
    market = daily_basic.drop_duplicates("ts_code").set_index("ts_code")
    portfolio["close"] = portfolio["ts_code"].map(pd.to_numeric(market["close"], errors="coerce"))

    holdings_path = output_dir / "portfolio_holdings_history.csv"
    nav_path = output_dir / "portfolio_nav_history.csv"
    dividend_ledger_path = output_dir / "portfolio_dividend_ledger.csv"
    old_holdings = pd.read_csv(holdings_path) if holdings_path.exists() else pd.DataFrame()
    nav = pd.read_csv(nav_path) if nav_path.exists() else pd.DataFrame()
    for column in NAV_DIVIDEND_COLUMNS:
        if column not in nav:
            nav[column] = 0.0
    dividend_events = _load_dividend_events()
    dividend_ledger = _prepare_dividend_ledger(dividend_ledger_path, as_of)

    if nav.empty:
        row = {"date": as_of, "nav": 1.0, "daily_return": 0.0, "price_coverage": 1.0,
               **{column: 0.0 for column in NAV_DIVIDEND_COLUMNS}}
        nav = pd.DataFrame([row])
    elif as_of not in nav["date"].astype(str).values:
        previous_date = str(nav.iloc[-1]["date"])
        previous = old_holdings[old_holdings["date"].astype(str).eq(previous_date)].copy()
        current_prices = pd.to_numeric(previous["ts_code"].map(market["close"]), errors="coerce")
        previous_prices = pd.to_numeric(previous["close"], errors="coerce")
        weights = pd.to_numeric(previous["target_weight"], errors="coerce").fillna(0)
        valid = current_prices.gt(0) & previous_prices.gt(0)
        events_today = dividend_events[dividend_events["ex_date"].eq(as_of)].copy()
        event_cash = events_today.groupby("ts_code")["cash_div"].sum() if not events_today.empty else pd.Series(dtype=float)
        event_stock = events_today.groupby("ts_code")["stk_div"].sum() if not events_today.empty else pd.Series(dtype=float)
        cash_per_share = previous["ts_code"].map(event_cash).fillna(0.0).astype(float)
        stock_per_share = previous["ts_code"].map(event_stock).fillna(0.0).astype(float)
        price_return = float((weights[valid] * (current_prices[valid] / previous_prices[valid] - 1)).sum())
        cash_dividend_return = float((weights[valid] * cash_per_share[valid] / previous_prices[valid]).sum())
        stock_dividend_return = float((
            weights[valid] * stock_per_share[valid] * current_prices[valid] / previous_prices[valid]
        ).sum())
        daily_return = price_return + cash_dividend_return + stock_dividend_return
        coverage = float(weights[valid].sum())
        previous_nav = float(nav.iloc[-1]["nav"])
        dividend_cash_per_unit = previous_nav * cash_dividend_return

        if not events_today.empty and dividend_cash_per_unit > 0:
            for _, holding in previous.loc[valid].iterrows():
                code = str(holding["ts_code"])
                code_events = events_today[events_today["ts_code"].eq(code)]
                if code_events.empty:
                    continue
                prior_close = float(holding["close"])
                weight = float(holding["target_weight"])
                for _, event in code_events.iterrows():
                    cash = float(event.get("cash_div", 0.0))
                    if cash <= 0 or prior_close <= 0:
                        continue
                    event_id = "|".join([
                        code, str(event.get("end_date", "")), str(event.get("ex_date", "")),
                        f"{cash:.8f}", f"{float(event.get('stk_div', 0.0)):.8f}",
                    ])
                    if dividend_ledger["event_id"].eq(event_id).any():
                        continue
                    pay_date = str(event.get("pay_date", ""))
                    paid_now = bool(pay_date and pay_date <= as_of)
                    dividend_ledger = pd.concat([dividend_ledger, pd.DataFrame([{
                        "event_id": event_id, "ts_code": code, "name": holding.get("name", ""),
                        "ex_date": str(event.get("ex_date", "")), "pay_date": pay_date,
                        "cash_div_per_share": cash,
                        "entitlement_per_unit": previous_nav * weight * cash / prior_close,
                        "status": "PAID_PENDING" if paid_now else "RECEIVABLE",
                        "paid_date": pay_date if paid_now else "", "reinvest_date": "",
                    }])], ignore_index=True)

        cumulative_dividend = float(nav.iloc[-1].get("cumulative_dividend_cash", 0.0)) + dividend_cash_per_unit
        reinvested_dividend = float(dividend_ledger.loc[
            dividend_ledger["status"].eq("REINVESTED"), "entitlement_per_unit"
        ].sum())
        pending_dividend = float(dividend_ledger.loc[
            dividend_ledger["status"].eq("PAID_PENDING"), "entitlement_per_unit"
        ].sum())
        dividend_receivable = float(dividend_ledger.loc[
            dividend_ledger["status"].eq("RECEIVABLE"), "entitlement_per_unit"
        ].sum())
        nav = pd.concat([nav, pd.DataFrame([{
            "date": as_of,
            "nav": previous_nav * (1 + daily_return),
            "daily_return": daily_return,
            "price_coverage": coverage,
            "price_return": price_return,
            "cash_dividend_return": cash_dividend_return,
            "stock_dividend_return": stock_dividend_return,
            "dividend_cash_per_unit": dividend_cash_per_unit,
            "cumulative_dividend_cash": cumulative_dividend,
            "reinvested_dividend_cash": reinvested_dividend,
            "pending_dividend_cash": pending_dividend,
            "dividend_receivable": dividend_receivable,
        }])], ignore_index=True)

    snapshot = portfolio[["ts_code", "name", "allocation_bucket", "target_weight", "close"]].copy()
    snapshot.insert(0, "date", as_of)
    if not old_holdings.empty:
        old_holdings = old_holdings[~old_holdings["date"].astype(str).eq(as_of)]
    old_holdings = pd.concat([old_holdings, snapshot], ignore_index=True)
    old_holdings.to_csv(holdings_path, index=False, encoding="utf-8-sig")
    nav.to_csv(nav_path, index=False, encoding="utf-8-sig")
    dividend_ledger.to_csv(dividend_ledger_path, index=False, encoding="utf-8-sig")


def export_portfolio_site_data(output_dir: Path, destination: Path) -> Path:
    """Export the latest strategy result as a browser-safe JSON snapshot."""
    portfolio = pd.read_csv(output_dir / "target_portfolio.csv")
    summary = pd.read_csv(output_dir / "portfolio_summary.csv").iloc[0]
    anchors = pd.read_csv(output_dir / "anchor_screen.csv").set_index("ts_code")
    future = pd.read_csv(output_dir / "future_states.csv").set_index("ts_code")
    moat_registry = pd.read_csv(MOAT_REGISTRY_PATH)
    moat_evidence = pd.read_csv(MOAT_EVIDENCE_PATH)
    moat_monitor = build_moat_monitor(moat_registry, moat_evidence, str(summary["as_of_date"])).set_index("ts_code")
    moat_alerts = pd.read_csv(MOAT_ALERTS_PATH) if MOAT_ALERTS_PATH.exists() else pd.DataFrame()
    if not moat_alerts.empty:
        moat_alerts = moat_alerts[moat_alerts["review_status"].eq("PENDING_REVIEW")].copy()
    moat_health_frame = pd.read_csv(MOAT_HEALTH_PATH) if MOAT_HEALTH_PATH.exists() else pd.DataFrame()
    moat_health = moat_health_frame.iloc[-1] if not moat_health_frame.empty else pd.Series(dtype=object)
    stock_distribution, distribution_summary, latest_returns = _portfolio_distribution(portfolio)

    holdings = []
    for row in portfolio.to_dict("records"):
        code = str(row["ts_code"])
        item = {
            "code": code,
            "name": row["name"],
            "bucket": row["allocation_bucket"],
            "state": row["strategy_state"],
            "theme": row["theme"],
            "industry": row.get("l1_name") if pd.notna(row.get("l1_name")) else "未分类",
            "weight": _number(row["target_weight"]),
            "price": 0.0,
            "dailyReturn": latest_returns[code],
            "distribution": stock_distribution[code],
        }
        if code in moat_monitor.index:
            moat = moat_monitor.loc[code]
            company_alerts = moat_alerts[moat_alerts["ts_code"].astype(str).eq(code)].copy() if not moat_alerts.empty else pd.DataFrame()
            if not company_alerts.empty:
                company_alerts = company_alerts.sort_values(["alert_date", "alert_level"], ascending=[False, True])
            latest_alert = company_alerts.iloc[0] if not company_alerts.empty else pd.Series(dtype=object)
            item["moat"] = {
                "type": str(moat.get("moat_type", "")),
                "thesis": str(moat.get("moat_thesis", "")),
                "replicationBarrier": str(moat.get("replication_barrier", "")),
                "monitoringSignals": [value for value in str(moat.get("monitoring_signals", "")).split("|") if value],
                "invalidationSignals": [value for value in str(moat.get("invalidation_signals", "")).split("|") if value],
                "status": str(moat.get("moat_status", "DRAFT")),
                "recommendedAction": str(moat.get("recommended_action", "")),
                "lastReviewDate": str(moat.get("last_review_date", "")),
                "nextReviewDate": str(moat.get("next_review_date", "")),
                "supportingEvidenceCount": int(moat.get("supporting_evidence_count", 0)),
                "cautionEvidenceCount": int(moat.get("caution_evidence_count", 0)),
                "contradictoryEvidenceCount": int(moat.get("contradictory_evidence_count", 0)),
                "radar": {
                    "pendingAlertCount": int(len(company_alerts)),
                    "highAlertCount": int(company_alerts["alert_level"].eq("HIGH").sum()) if not company_alerts.empty else 0,
                    "latestAlertDate": str(latest_alert.get("alert_date", "")),
                    "latestAlertTitle": str(latest_alert.get("title", "")),
                    "latestAlertSource": str(latest_alert.get("alert_source", "")),
                },
            }
        if row["allocation_bucket"] == "ANCHOR" and code in anchors.index:
            detail = anchors.loc[code]
            item["price"] = _number(detail.get("close"))
            item["metrics"] = {
                "股息率": f"{_number(detail.get('dv_ratio')):.1f}%",
                "所有者收益率": f"{_number(detail.get('owner_earnings_yield')):.1%}",
                "三年ROE": f"{_number(detail.get('normalized_roe')):.1%}",
                "护城河代理分": f"{_number(detail.get('moat_proxy_score')):.1f}",
            }
        elif code in future.index:
            detail = future.loc[code]
            item["price"] = _number(detail.get("close"))
            item["metrics"] = {
                "未来逻辑分": f"{_number(detail.get('future_thesis_score')):.1f}",
                "DCF安全边际": f"{_number(detail.get('dcf_margin_of_safety')):.1%}",
                "当前状态": str(detail.get("timing_status", "—")),
            }
        holdings.append(item)

    pending = anchors[anchors["anchor_financial_check"].eq("NOT_FETCHED")]
    nav_path = output_dir / "portfolio_nav_history.csv"
    nav_frame = pd.read_csv(nav_path).tail(60) if nav_path.exists() else pd.DataFrame()
    nav_history = nav_frame.to_dict("records")
    latest_nav = nav_frame.iloc[-1] if not nav_frame.empty else pd.Series(dtype=float)
    data = {
        "asOf": str(summary["as_of_date"]),
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "summary": {
            "anchorWeight": _number(summary["anchor_weight"]),
            "futureWeight": _number(summary["future_weight"]),
            "cashWeight": _number(summary["cash_weight"]),
            "universeScanned": int(summary["anchor_universe_scanned"]),
            "financialReviewed": int(summary["anchor_financial_reviewed"]),
            "financialComplete": int(summary["anchor_financial_complete"]),
            "anchorEligible": int(summary["anchor_eligible"]),
        },
        "holdings": holdings,
        "moatRadar": {
            "asOf": str(moat_health.get("as_of_date", summary["as_of_date"])),
            "checkedAt": str(moat_health.get("checked_at", "")),
            "announcementStatus": str(moat_health.get("announcement_status", "NOT_RUN")),
            "financialStatus": str(moat_health.get("financial_status", "NOT_RUN")),
            "pendingAlerts": int(_number(moat_health.get("pending_alerts", 0))),
            "highAlerts": int(_number(moat_health.get("high_alerts", 0))),
            "announcementRowsInWindow": int(_number(moat_health.get("announcement_rows_in_window", 0))),
            "note": "规则命中只生成待人工复核事件，不会自动改变护城河结论或触发交易",
        },
        "distributionSummary": distribution_summary,
        "dividendSummary": {
            "cumulativeCash": _number(latest_nav.get("cumulative_dividend_cash", 0.0)),
            "reinvestedCash": _number(latest_nav.get("reinvested_dividend_cash", 0.0)),
            "pendingCash": _number(latest_nav.get("pending_dividend_cash", 0.0)),
            "receivableCash": _number(latest_nav.get("dividend_receivable", 0.0)),
            "accountingBasis": "Tushare cash_div after-tax proxy; ex-date entitlement, pay-date cash, next-session target-weight reinvestment",
        },
        "navHistory": [{
            "date": str(row["date"]),
            "nav": _number(row["nav"], 1.0),
            "dailyReturn": _number(row["daily_return"]),
            "priceCoverage": _number(row["price_coverage"], 1.0),
            "cashDividendReturn": _number(row.get("cash_dividend_return", 0.0)),
            "stockDividendReturn": _number(row.get("stock_dividend_return", 0.0)),
        } for row in nav_history],
        "pendingFinancials": pending["name"].dropna().astype(str).tolist(),
        "logic": [
            {"step": "01", "title": "先建立护城河锚", "body": "先要求细分行业领先，再用长期毛利率、ROE、收入韧性与现金转化识别品牌溢价或规模成本优势；这些是研究代理，不把高股息直接当护城河。"},
            {"step": "02", "title": "再保留未来期权", "body": "只从国家规划与明确需求链中选择少量公司；产业逻辑、价值支撑和底部位置同时通过后，先给2.5%试错仓。"},
            {"step": "03", "title": "分级确认，双向升降", "body": "种子仓从2.5%开始；至少两类产业里程碑得到验证后升至5%，三类全部验证且趋势确认后升至7.5%。证据退化时按相同阶梯减仓。"},
            {"step": "04", "title": "剩余预算留现金", "body": "不为了满仓降低标准。没有足够合格标的、行业达到上限或证据缺失时，预算自动保留为现金。"},
        ],
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return destination
