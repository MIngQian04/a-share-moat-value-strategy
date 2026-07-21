from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from selection.moat_monitor import build_moat_monitor


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TRADING_DAYS = 252
DIVIDEND_EVENTS_PATH = PROJECT_ROOT / "data/processed/portfolio/dividend_events.csv"
MOAT_REGISTRY_PATH = PROJECT_ROOT / "config/moat-thesis-registry.csv"
MOAT_EVIDENCE_PATH = PROJECT_ROOT / "config/moat-evidence-ledger.csv"
HUMAN_MOAT_REVIEW_PATH = PROJECT_ROOT / "config/moat-human-review.csv"
MOAT_ALERTS_PATH = PROJECT_ROOT / "outputs/barbell-strategy/moat_radar_alerts.csv"
MOAT_HEALTH_PATH = PROJECT_ROOT / "outputs/barbell-strategy/moat_radar_health.csv"
VALUATION_WARNINGS_PATH = PROJECT_ROOT / "outputs/barbell-strategy/future_valuation_warnings.csv"
VALUATION_REPAIR_BRIEFS_PATH = PROJECT_ROOT / "config/valuation-repair-briefs.json"
DIVIDEND_LEDGER_COLUMNS = [
    "event_id", "ts_code", "name", "ex_date", "pay_date", "cash_div_per_share",
    "entitlement_per_unit", "status", "paid_date", "reinvest_date",
]
NAV_DIVIDEND_COLUMNS = [
    "price_return", "cash_dividend_return", "stock_dividend_return",
    "dividend_cash_per_unit", "cumulative_dividend_cash",
    "reinvested_dividend_cash", "pending_dividend_cash", "dividend_receivable",
]
BENCHMARK_PATH = PROJECT_ROOT / "data/processed/index_benchmark.csv"
BENCHMARK_CODE = "000300.SH"
BENCHMARK_NAME = "沪深300"
BENCHMARK_NAME_EN = "CSI 300"


def _normalize_benchmark_dates(values: pd.Series) -> pd.Series:
    raw_dates = values.astype(str).str.strip()
    normalized = pd.to_datetime(raw_dates, format="%Y%m%d", errors="coerce")
    normalized = normalized.fillna(pd.to_datetime(raw_dates, errors="coerce"))
    return normalized.dt.strftime("%Y-%m-%d")


def _refresh_benchmark_cache(nav_dates: list[str]) -> None:
    """Best-effort refresh of missing CSI 300 dates; never fabricates values."""
    if not nav_dates:
        return
    cached = pd.DataFrame()
    if BENCHMARK_PATH.exists():
        try:
            cached = pd.read_csv(BENCHMARK_PATH)
            if "trade_date" in cached:
                cached["trade_date"] = _normalize_benchmark_dates(cached["trade_date"])
        except (OSError, pd.errors.ParserError):
            cached = pd.DataFrame()
    cached_dates = set(cached.get("trade_date", pd.Series(dtype=str)).dropna().astype(str))
    missing = [date for date in nav_dates if date not in cached_dates]
    if not missing:
        return
    load_dotenv(PROJECT_ROOT / ".env")
    token = os.getenv("TUSHARE_TOKEN") or os.getenv("TS_TOKEN") or os.getenv("TUSHARE_API_TOKEN")
    if not token:
        return
    try:
        import tushare as ts
        ts.set_token(token)
        raw = ts.pro_api().index_daily(
            ts_code=BENCHMARK_CODE,
            start_date=min(nav_dates).replace("-", ""),
            end_date=max(nav_dates).replace("-", ""),
        )
    except Exception:
        return
    if raw is None or raw.empty or "trade_date" not in raw or "close" not in raw:
        return
    raw = raw.copy()
    raw["trade_date"] = _normalize_benchmark_dates(raw["trade_date"])
    merged = pd.concat([cached, raw], ignore_index=True) if not cached.empty else raw
    merged = merged.drop_duplicates(["trade_date", "ts_code"] if "ts_code" in merged else ["trade_date"], keep="last")
    merged = merged.sort_values("trade_date")
    BENCHMARK_PATH.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(BENCHMARK_PATH, index=False, encoding="utf-8-sig")


def _benchmark_history(nav_dates: list[str]) -> dict:
    """Build a same-date, unit-1 CSI 300 price proxy for the public site.

    The benchmark intentionally uses the raw index close, not a dividend-adjusted
    series.  Missing dates are reported explicitly instead of being filled from
    the portfolio or treated as zero returns.
    """
    result = {
        "code": BENCHMARK_CODE,
        "name": BENCHMARK_NAME,
        "nameEn": BENCHMARK_NAME_EN,
        "basis": "沪深300原始收盘价指数代理，不含指数分红；与组合同一记录日归一化为1",
        "basisEn": "CSI 300 raw close proxy, excluding index dividends; normalized to 1 on the same recorded dates",
        "status": "UNAVAILABLE",
        "startDate": nav_dates[0] if nav_dates else "",
        "endDate": nav_dates[-1] if nav_dates else "",
        "history": [],
    }
    if not nav_dates or not BENCHMARK_PATH.exists():
        return result
    try:
        benchmark = pd.read_csv(BENCHMARK_PATH)
    except (OSError, pd.errors.ParserError):
        return result
    required = {"trade_date", "close"}
    if not required.issubset(benchmark.columns):
        return result
    benchmark = benchmark.copy()
    benchmark["trade_date"] = _normalize_benchmark_dates(benchmark["trade_date"])
    benchmark["close"] = pd.to_numeric(benchmark["close"], errors="coerce")
    benchmark = benchmark[benchmark["close"].gt(0)].drop_duplicates("trade_date", keep="last")
    by_date = benchmark.set_index("trade_date")["close"]
    missing = [date for date in nav_dates if date not in by_date.index]
    if missing:
        result["status"] = "PARTIAL" if any(date in by_date.index for date in nav_dates) else "UNAVAILABLE"
        result["missingDates"] = missing
        return result
    closes = [float(by_date.loc[date]) for date in nav_dates]
    base = closes[0]
    units = [close / base for close in closes]
    history = []
    for index, (date, unit) in enumerate(zip(nav_dates, units)):
        previous = units[index - 1] if index else 1.0
        history.append({
            "date": date,
            "nav": unit,
            "dailyReturn": unit / previous - 1 if previous else 0.0,
        })
    result.update({
        "status": "OK",
        "history": history,
        "startDate": nav_dates[0],
        "endDate": nav_dates[-1],
    })
    return result


def _allocation_change_reason(change_type: str, bucket: str, detail: str = "") -> str:
    if detail and ("DCF" in detail or "估值" in detail):
        return detail
    if bucket == "FUTURE":
        if change_type == "退出":
            return "当前未来产业证据或时点门槛未达到入选要求，回到观察状态并把预算留在现金；不等于自动判定产业逻辑失效。"
        return "未来产业小种子仍有政策、需求、价值和现金收益证据支持，但里程碑尚未满足晋级条件，因此只保留阶梯起点仓位。"
    if change_type == "新增":
        return "本轮稳定锚重筛选中通过细分行业地位、护城河代理和现金收益质量等机械门槛，因此进入目标组合；护城河原始证据仍需人工核验。"
    if change_type == "退出":
        return "本轮稳定锚重筛选与经济因子分散后不再占用目标名额，目标权重归零；这是组合门槛结果，不等于自动判定护城河失效。"
    return "通过门槛的标的按总锚仓、现金比例和经济因子分散约束重新归一化，因此目标权重被上调或下调；不是按当日价格追涨杀跌。"


def _number(value, default=0.0):
    return default if pd.isna(value) else float(value)


def _load_human_moat_review() -> dict[str, bool]:
    """Load the explicit human yes/no review status; missing rows stay false."""
    if not HUMAN_MOAT_REVIEW_PATH.exists():
        return {}
    review = pd.read_csv(HUMAN_MOAT_REVIEW_PATH)
    if "ts_code" not in review or "confirmed" not in review:
        return {}
    values = review[["ts_code", "confirmed"]].copy()
    values["ts_code"] = values["ts_code"].astype(str)
    values["confirmed"] = values["confirmed"].astype(str).str.strip().str.lower().isin(
        {"true", "yes", "y", "1", "是", "已确认"}
    )
    return values.drop_duplicates("ts_code", keep="last").set_index("ts_code")["confirmed"].to_dict()


def _load_valuation_repair_briefs() -> dict:
    if not VALUATION_REPAIR_BRIEFS_PATH.exists():
        return {}
    try:
        return json.loads(VALUATION_REPAIR_BRIEFS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _valuation_repair_brief(code: str, detail: pd.Series, briefs: dict) -> dict:
    """Return a review aid; it is never an automatic moat or allocation decision."""
    configured = dict(briefs.get(code, {}))
    current_price = _number(detail.get("close"))
    base_value = _number(detail.get("dcf_base_value_per_share"), default=float("nan"))
    margin = _number(detail.get("dcf_base_margin_of_safety"), default=float("nan"))
    if pd.isna(margin) and current_price > 0 and pd.notna(base_value):
        margin = base_value / current_price - 1
    configured.setdefault("asOf", "")
    configured.setdefault("generatedBy", "本地AI研究辅助：基于当前缓存财务、DCF和公开资料整理")
    configured.setdefault("generatedByEn", "Local AI research aid: current cached financials, DCF and public information")
    configured.setdefault("undervaluationReasons", [])
    configured.setdefault("repairConditions", [])
    configured.setdefault("failureSignals", [])
    configured.setdefault("institutionReferences", [])
    configured["currentPrice"] = current_price
    configured["baseDcfValuePerShare"] = None if pd.isna(base_value) else base_value
    configured["baseDcfMargin"] = None if pd.isna(margin) else margin
    optimistic_value = _number(detail.get("dcf_optimistic_value_per_share"), default=float("nan"))
    configured["optimisticDcfValuePerShare"] = None if pd.isna(optimistic_value) else optimistic_value
    reference_targets = [
        _number(reference.get("targetPrice"), default=float("nan"))
        for reference in configured.get("institutionReferences", [])
    ]
    reference_targets = [target for target in reference_targets if pd.notna(target) and target > 0]
    lowest_reference = min(reference_targets) if reference_targets else float("nan")
    configured["institutionReferencePrice"] = None if pd.isna(lowest_reference) else lowest_reference
    configured["institutionReferenceAboveOptimistic"] = bool(
        reference_targets and pd.notna(optimistic_value) and lowest_reference > optimistic_value
    )
    configured["valuationRule"] = "HOLD" if configured["institutionReferenceAboveOptimistic"] else "REVIEW"
    configured.setdefault("disclaimer", "这是辅助研究，不是自动买卖信号；机构目标价是公开预测，需结合发布日期、货币和假设自行判断。")
    configured.setdefault("disclaimerEn", "This is a research aid, not an automatic trading signal; institution targets are public forecasts and should be assessed with their dates, currencies and assumptions.")
    return configured


def _dcf_valuation(detail: pd.Series) -> dict | None:
    """Expose the five discount-rate cases without changing the base gate."""
    cases = {}
    for scenario in ["very_optimistic", "optimistic", "base", "cautious", "very_pessimistic"]:
        rate = detail.get(f"dcf_{scenario}_discount_rate")
        value = detail.get(f"dcf_{scenario}_value_per_share")
        margin = detail.get(f"dcf_{scenario}_margin_of_safety")
        if pd.isna(rate) and pd.isna(value) and pd.isna(margin):
            continue
        cases[scenario] = {
            "discountRate": _number(rate),
            "valuePerShare": _number(value),
            "marginOfSafety": _number(margin),
        }
    return cases or None


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
    """Describe trailing return distributions for the currently active holdings."""
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
        "method": "当日生效仓位的近252个共同交易日；偏度描述方向，峰度为超额峰度并描述极端波动频率",
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
    """Append an idempotent prior-target close-to-close total-return observation.

    Raw close returns are augmented on the ex-date by Tushare's after-tax cash
    dividend and stock-dividend ratios. Cash entitlements are tracked through
    receivable, paid-pending and next-session target-weight reinvestment states.
    The target published on the previous completed session earns the entire
    current session; the current post-close target is only queued for the next
    session and never contributes to today's return.
    """
    portfolio = pd.read_csv(output_dir / "target_portfolio.csv")
    summary = pd.read_csv(output_dir / "portfolio_summary.csv").iloc[0]
    as_of = str(summary["as_of_date"])
    market = daily_basic.drop_duplicates("ts_code").set_index("ts_code")
    close_series = pd.to_numeric(market["close"], errors="coerce") if "close" in market else pd.Series(dtype=float)
    open_series = pd.to_numeric(market["open"], errors="coerce") if "open" in market else pd.Series(dtype=float)
    portfolio["close"] = portfolio["ts_code"].map(close_series)
    # Cached offline snapshots may contain only official closes.  Keep the
    # execution-proxy field empty rather than treating a close as an open fill.
    portfolio["open"] = portfolio["ts_code"].map(open_series)

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
        current_closes = pd.to_numeric(previous["ts_code"].map(market["close"]), errors="coerce")
        previous_prices = pd.to_numeric(previous["close"], errors="coerce")
        previous_weights = pd.to_numeric(previous["target_weight"], errors="coerce").fillna(0)
        valid_close_to_close = current_closes.gt(0) & previous_prices.gt(0)
        events_today = dividend_events[dividend_events["ex_date"].eq(as_of)].copy()
        event_cash = events_today.groupby("ts_code")["cash_div"].sum() if not events_today.empty else pd.Series(dtype=float)
        event_stock = events_today.groupby("ts_code")["stk_div"].sum() if not events_today.empty else pd.Series(dtype=float)
        cash_per_share = previous["ts_code"].map(event_cash).fillna(0.0).astype(float)
        stock_per_share = previous["ts_code"].map(event_stock).fillna(0.0).astype(float)
        price_return = float((previous_weights[valid_close_to_close] * (current_closes[valid_close_to_close] / previous_prices[valid_close_to_close] - 1)).sum())
        cash_dividend_return = float((previous_weights[valid_close_to_close] * cash_per_share[valid_close_to_close] / previous_prices[valid_close_to_close]).sum())
        stock_dividend_return = float((
            previous_weights[valid_close_to_close] * stock_per_share[valid_close_to_close] * current_closes[valid_close_to_close] / previous_prices[valid_close_to_close]
        ).sum())
        daily_return = price_return + cash_dividend_return + stock_dividend_return
        coverage = float(previous_weights[valid_close_to_close].sum())
        previous_nav = float(nav.iloc[-1]["nav"])
        dividend_cash_per_unit = previous_nav * cash_dividend_return

        if not events_today.empty and dividend_cash_per_unit > 0:
            for _, holding in previous.loc[valid_close_to_close].iterrows():
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

    snapshot = portfolio[["ts_code", "name", "allocation_bucket", "target_weight", "open", "close"]].copy()
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
    valuation_warnings = pd.read_csv(VALUATION_WARNINGS_PATH) if VALUATION_WARNINGS_PATH.exists() else pd.DataFrame()
    if not valuation_warnings.empty and "status" in valuation_warnings:
        valuation_warnings = valuation_warnings[valuation_warnings["status"].isin({"WARNING", "EXIT_DUE"})].copy()
    moat_registry = pd.read_csv(MOAT_REGISTRY_PATH)
    moat_evidence = pd.read_csv(MOAT_EVIDENCE_PATH)
    human_moat_review = _load_human_moat_review()
    valuation_repair_briefs = _load_valuation_repair_briefs()
    moat_monitor = build_moat_monitor(moat_registry, moat_evidence, str(summary["as_of_date"])).set_index("ts_code")
    moat_alerts = pd.read_csv(MOAT_ALERTS_PATH) if MOAT_ALERTS_PATH.exists() else pd.DataFrame()
    if not moat_alerts.empty:
        moat_alerts = moat_alerts[moat_alerts["review_status"].eq("PENDING_REVIEW")].copy()
    moat_health_frame = pd.read_csv(MOAT_HEALTH_PATH) if MOAT_HEALTH_PATH.exists() else pd.DataFrame()
    moat_health = moat_health_frame.iloc[-1] if not moat_health_frame.empty else pd.Series(dtype=object)

    holdings_path = output_dir / "portfolio_holdings_history.csv"
    history = pd.read_csv(holdings_path) if holdings_path.exists() else pd.DataFrame()
    previous_date = ""
    previous_rows = pd.DataFrame()
    if not history.empty:
        dates = sorted(history["date"].astype(str).unique())
        prior_dates = [date for date in dates if date < str(summary["as_of_date"])]
        if prior_dates:
            previous_date = prior_dates[-1]
            previous_rows = history[history["date"].astype(str).eq(previous_date)].copy()
    active_distribution_portfolio = previous_rows if not previous_rows.empty else portfolio
    stock_distribution, distribution_summary, latest_returns = _portfolio_distribution(active_distribution_portfolio)
    export_rows = pd.concat([portfolio, previous_rows], ignore_index=True).drop_duplicates("ts_code", keep="first")
    holdings = []
    for row in export_rows.to_dict("records"):
        code = str(row["ts_code"])
        item = {
            "code": code,
            "name": row["name"],
            "bucket": row["allocation_bucket"],
            "state": row.get("strategy_state", row.get("allocation_bucket", "")) if pd.notna(row.get("strategy_state", row.get("allocation_bucket", ""))) else "",
            "theme": row.get("theme", "稳定现金流") if pd.notna(row.get("theme", "稳定现金流")) else "稳定现金流",
            "industry": row.get("l1_name") if pd.notna(row.get("l1_name")) else "未分类",
            "weight": _number(row["target_weight"]),
            "price": 0.0,
            "dailyReturn": latest_returns.get(code, 0.0),
            "reason": str(row.get("reason", "")),
            "humanMoatConfirmed": bool(human_moat_review.get(code, False)),
            "distribution": stock_distribution.get(code, _distribution_metrics(pd.Series(dtype=float))),
        }
        company_alerts = moat_alerts[moat_alerts["ts_code"].astype(str).eq(code)].copy() if not moat_alerts.empty else pd.DataFrame()
        if not company_alerts.empty:
            company_alerts = company_alerts.sort_values(["alert_date", "alert_level"], ascending=[False, True])
        latest_alert = company_alerts.iloc[0] if not company_alerts.empty else pd.Series(dtype=object)
        moat = moat_monitor.loc[code] if code in moat_monitor.index else pd.Series(dtype=object)
        item["moat"] = {
            "type": str(moat.get("moat_type", "档案待补全")),
            "thesis": str(moat.get("moat_thesis", "该持仓尚未建立护城河假设；不得据此推断护城河存在。")),
            "replicationBarrier": str(moat.get("replication_barrier", "需补充可追溯的一手资料后判断。")),
            "monitoringSignals": [value for value in str(moat.get("monitoring_signals", "等待建立监测指标")).split("|") if value],
            "invalidationSignals": [value for value in str(moat.get("invalidation_signals", "未建立档案前禁止扩大仓位")).split("|") if value],
            "status": str(moat.get("moat_status", "DRAFT")),
            "recommendedAction": str(moat.get("recommended_action", "暂停加仓，先补齐可追溯的一手证据和护城河假设。")),
            "lastReviewDate": str(moat.get("last_review_date", "")),
            "nextReviewDate": str(moat.get("next_review_date", "待建立")),
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
            item["valuation"] = _dcf_valuation(detail)
            item["metrics"] = {
                "股息率": f"{_number(detail.get('dv_ratio')):.1f}%",
                "所有者收益率": f"{_number(detail.get('owner_earnings_yield')):.1%}",
                "三年ROE": f"{_number(detail.get('normalized_roe')):.1%}",
                "护城河代理分": f"{_number(detail.get('moat_proxy_score')):.1f}",
            }
            item["valuationRepair"] = _valuation_repair_brief(code, detail, valuation_repair_briefs)
        elif code in future.index:
            detail = future.loc[code]
            item["price"] = _number(detail.get("close"))
            item["valuation"] = _dcf_valuation(detail)
            item["metrics"] = {
                "未来逻辑分": f"{_number(detail.get('future_thesis_score')):.1f}",
                "DCF安全边际": f"{_number(detail.get('dcf_margin_of_safety')):.1%}",
                "当前状态": str(detail.get("timing_status", "—")),
            }
            item["valuationRepair"] = _valuation_repair_brief(code, detail, valuation_repair_briefs)
        holdings.append(item)

    next_codes = set(portfolio["ts_code"].astype(str))
    active_codes = set(previous_rows["ts_code"].astype(str)) if not previous_rows.empty else next_codes
    by_code = {item["code"]: item for item in holdings}
    active_holdings = []
    for code in active_codes:
        if code not in by_code:
            continue
        item = dict(by_code[code])
        previous_weight = previous_rows.loc[previous_rows["ts_code"].astype(str).eq(code), "target_weight"]
        if not previous_weight.empty:
            item["weight"] = _number(previous_weight.iloc[0])
        item["reason"] = "上一交易日已公布仓位"
        active_holdings.append(item)
    next_holdings = [item for item in holdings if item["code"] in next_codes]

    # The visible Today figure must be the published NAV observation, which is
    # calculated from the prior target using the raw close/dividend ledger. Do
    # not reconstruct it from the distribution portrait's adjusted closes.
    nav_path = output_dir / "portfolio_nav_history.csv"
    nav_observations = pd.read_csv(nav_path) if nav_path.exists() else pd.DataFrame()
    latest_nav_observation = nav_observations.iloc[-1] if not nav_observations.empty else pd.Series(dtype=float)
    model_daily_return = _number(latest_nav_observation.get("daily_return", 0.0))

    confirmed_active_weight = sum(
        float(item["weight"]) for item in active_holdings if item["humanMoatConfirmed"]
    )
    gray_active_weight = sum(
        float(item["weight"]) for item in active_holdings if not item["humanMoatConfirmed"]
    )
    model_active_return = model_daily_return
    confirmed_active_return = sum(
        float(item["weight"]) * float(item["dailyReturn"])
        for item in active_holdings if item["humanMoatConfirmed"]
    )
    gray_active_return = sum(
        float(item["weight"]) * float(item["dailyReturn"])
        for item in active_holdings if not item["humanMoatConfirmed"]
    )
    human_review_summary = {
        "confirmedCount": int(sum(item["humanMoatConfirmed"] for item in active_holdings)),
        "totalCount": len(active_holdings),
        "confirmedWeight": confirmed_active_weight,
        "grayWeight": gray_active_weight,
        "modelDailyReturn": model_active_return,
        "confirmedDailyReturn": confirmed_active_return if confirmed_active_weight > 0 else None,
        "grayDailyReturn": gray_active_return if gray_active_weight > 0 else None,
        "note": "人工护城河判断仅用于观察和预警，不是持仓或收益计算门槛；模型按目标仓位计算全部持仓收益，出现有据可查的不利证据时再触发复核。",
    }
    active_cash_weight = max(0.0, 1.0 - sum(float(item["weight"]) for item in active_holdings))
    changes = []
    for code in sorted(active_codes | next_codes):
        old = next((item for item in active_holdings if item["code"] == code), None)
        new = next((item for item in next_holdings if item["code"] == code), None)
        old_weight = old["weight"] if old else 0.0
        new_weight = new["weight"] if new else 0.0
        if abs(old_weight - new_weight) < 1e-9:
            continue
        change_type = "新增" if not old else "退出" if not new else "增仓" if new_weight > old_weight else "减仓"
        changed_item = new or old
        detail = str(new.get("reason", "")).strip() if new else ""
        changes.append({
            "code": code,
            "name": (new or old)["name"],
            "oldWeight": old_weight,
            "newWeight": new_weight,
            "changeType": change_type,
            "reason": detail or _allocation_change_reason(change_type, str(changed_item.get("bucket", "ANCHOR"))),
            "effect": "仅作为下一交易日目标信号；不会回溯修改今日收益，也不会自动下单。",
        })
    valuation_warning_rows = []
    if not valuation_warnings.empty:
        for row in valuation_warnings.to_dict("records"):
            valuation_warning_rows.append({
                "code": str(row.get("ts_code", "")),
                "name": str(row.get("name", "")),
                "status": str(row.get("status", "")),
                "warningDate": str(row.get("warning_date", "")),
                "consecutiveDays": int(_number(row.get("consecutive_days", 0))),
                "cooldownSessionsRemaining": int(_number(row.get("cooldown_sessions_remaining", 0))),
                "dcfMargin": _number(row.get("dcf_margin_of_safety")),
                "premiumCap": _number(row.get("valuation_premium_cap")),
                "reason": str(row.get("reason", "")),
                "effect": "先预警再确认；确认后只减一档并进入冷静期，冷静期内不重复减仓；不因估值单独清仓。",
            })
    allocation_change = {
        "changed": bool(changes or valuation_warning_rows),
        "activeAsOf": previous_date or str(summary["as_of_date"]),
        "nextAsOf": str(summary["as_of_date"]),
        "effectiveLabel": "下一交易日开盘后生效",
        "marketContext": "本轮没有使用宏观大环境择时信号；变化只由个股筛选/证据状态、锚仓继承纪律、经济因子分散和现金预算约束驱动。",
        "changes": changes,
        "valuationWarnings": valuation_warning_rows,
    }
    pending = anchors[anchors["anchor_financial_check"].eq("NOT_FETCHED")]
    # Keep the complete forward ledger so the site can compare the strategy
    # with a benchmark from the actual restart date, not just the latest 60 rows.
    nav_frame = pd.read_csv(nav_path) if nav_path.exists() else pd.DataFrame()
    nav_history = nav_frame.to_dict("records")
    latest_nav = nav_frame.iloc[-1] if not nav_frame.empty else pd.Series(dtype=float)
    nav_dates = nav_frame["date"].astype(str).tolist() if not nav_frame.empty else []
    _refresh_benchmark_cache(nav_dates)
    benchmark = _benchmark_history(nav_dates)
    data = {
        "asOf": str(summary["as_of_date"]),
        "returnDate": str(nav_frame.iloc[-1]["date"]) if not nav_frame.empty else str(summary["as_of_date"]),
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "summary": {
            "anchorWeight": _number(summary["anchor_weight"]),
            "futureWeight": _number(summary["future_weight"]),
            "cashWeight": _number(summary["cash_weight"]),
            "activeCashWeight": active_cash_weight,
            "universeScanned": int(summary["anchor_universe_scanned"]),
            "financialReviewed": int(summary["anchor_financial_reviewed"]),
            "financialComplete": int(summary["anchor_financial_complete"]),
            "anchorEligible": int(summary["anchor_eligible"]),
        },
        "activeAsOf": previous_date or str(summary["as_of_date"]),
        "distributionAsOf": previous_date or str(summary["as_of_date"]),
        "holdings": active_holdings,
        "nextHoldings": next_holdings,
        "humanReview": human_review_summary,
        "allocationChange": allocation_change,
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
        "benchmark": benchmark,
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
