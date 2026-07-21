"""Build the current forward-looking barbell portfolio without a backtest gate."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import yaml

from data_loader.tushare_client import TushareClient
from portfolio.barbell_strategy import (
    anchor_signal_table,
    build_barbell_weights,
    build_full_market_anchor_universe,
    classify_future_states,
)
from portfolio.site_export import export_portfolio_site_data, update_portfolio_nav_history
from selection.evidence_registry import build_evidence_readiness
from selection.policy_alignment import apply_policy_alignment
from valuation.owner_earnings import owner_earnings_from_statements


OUT = Path("outputs/barbell-strategy")
POLICY_OUT = Path("outputs/policy-framework")
FIN = Path("data/raw/fundamental")


def anchor_financial_checks(watchlist: pd.DataFrame, daily: pd.DataFrame, refresh: bool,
                            fetch_missing: bool = True, discount_rate: float = 0.10,
                            discount_rate_step: float = 0.01) -> pd.DataFrame:
    client = TushareClient(data_dir="data/raw", max_retries=2, request_timeout_seconds=8) if refresh or fetch_missing else None
    market = daily.set_index("ts_code")
    rows = []
    for code in watchlist["ts_code"]:
        frames = []
        fetch_errors = []
        for endpoint in ["income", "cashflow", "balancesheet"]:
            path = FIN / endpoint / f"{code.replace('.', '_')}.parquet"
            if path.exists() and not refresh:
                frame = pd.read_parquet(path)
            elif client is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
                frame = pd.DataFrame()
                for attempt in range(client.max_retries):
                    try:
                        result = getattr(client.pro, endpoint)(ts_code=code, start_date="20190101")
                        frame = pd.DataFrame() if result is None else result
                        if not frame.empty:
                            frame.to_parquet(path, index=False)
                        time.sleep(client.sleep_seconds)
                        break
                    except Exception as exc:
                        if attempt + 1 == client.max_retries:
                            fetch_errors.append(f"{endpoint}: {type(exc).__name__}")
                        else:
                            time.sleep(client.sleep_seconds * (attempt + 1) * 4)
            else:
                frame = pd.DataFrame()
            frames.append(frame)
        if any(frame.empty for frame in frames) or code not in market.index:
            rows.append({"ts_code": code, "anchor_financial_check": "NOT_FETCHED",
                         "financial_error": "; ".join(fetch_errors)})
            continue
        row = market.loc[code]
        value = owner_earnings_from_statements(
            frames[0], frames[1], frames[2], float(row["total_share"]) * 10000.0,
            discount_rate=discount_rate, discount_rate_step=discount_rate_step,
        )
        market_cap = float(row["total_mv"]) * 10000.0
        owner_yield = value["normalized_owner_earnings"] / market_cap if market_cap > 0 else float("nan")
        check = "PASS_CASH_EARNINGS" if value["normalized_owner_earnings"] > 0 and value["normalized_fcf"] > 0 else "FAIL_CASH_EARNINGS"
        close = float(row["close"])
        for scenario in ["very_optimistic", "optimistic", "base", "cautious", "very_pessimistic"]:
            scenario_price = value.get(f"dcf_{scenario}_value_per_share")
            value[f"dcf_{scenario}_margin_of_safety"] = (
                scenario_price / close - 1 if pd.notna(scenario_price) and close > 0 else float("nan")
            )
        rows.append({"ts_code": code, **value, "owner_earnings_yield": owner_yield,
                     "anchor_financial_check": check, "financial_error": ""})
    return pd.DataFrame(rows)


def markdown_table(frame: pd.DataFrame, columns: list[str], labels: list[str]) -> str:
    if frame.empty:
        return "暂无。"
    shown = frame[columns].copy()
    if "target_weight" in shown:
        shown["target_weight"] = shown["target_weight"].map(lambda x: f"{x:.1%}")
    if "dcf_margin_of_safety" in shown:
        shown["dcf_margin_of_safety"] = pd.to_numeric(shown["dcf_margin_of_safety"], errors="coerce").map(
            lambda x: "—" if pd.isna(x) else f"{x:.1%}"
        )
    if "owner_earnings_yield" in shown:
        shown["owner_earnings_yield"] = pd.to_numeric(shown["owner_earnings_yield"], errors="coerce").map(
            lambda x: "—" if pd.isna(x) else f"{x:.1%}"
        )
    shown.columns = labels
    return shown.to_markdown(index=False)


def build_future_research_funnel(states: pd.DataFrame) -> pd.DataFrame:
    """Order future candidates and expose the first mechanical gate that failed."""
    out = states.copy()
    policy_sequence = {
        "NET_ENERGY": (1, "电网设备"),
        "NET_COMM": (2, "通信算力"),
        "NET_COMPUTE": (2, "通信算力"),
        "NET_TRANSPORT": (3, "轨交控制"),
        "NET_WATER": (4, "水务运营"),
        "EMERGING_AUTO_ROBOT": (5, "工业感知连接"),
        "FUTURE_EMBODIED_AI": (5, "工业感知连接"),
        "KEY_TECH_IC_INSTRUMENT": (5, "工业感知连接"),
    }
    mapped = out.get("policy_code", pd.Series("", index=out.index)).map(policy_sequence)
    out["research_sequence"] = mapped.map(lambda value: value[0] if isinstance(value, tuple) else 6)
    out["research_direction"] = mapped.map(lambda value: value[1] if isinstance(value, tuple) else "其他规划方向")

    def first_gate(row: pd.Series) -> str:
        if row.get("barbell_state") == "PROMOTED_CORE":
            return "PROMOTED_CORE"
        if row.get("barbell_state") == "CONFIRMED_BUILD":
            return "CONFIRMED_BUILD"
        if row.get("barbell_state") == "OPTION_SEED":
            return "OPTION_SEED"
        if row.get("barbell_state") == "VALUATION_REDUCTION":
            return "VALUATION_REDUCTION"
        if row.get("policy_status") != "POLICY_ELIGIBLE":
            return "POLICY_NOT_ELIGIBLE"
        if pd.to_numeric(row.get("future_thesis_score"), errors="coerce") < 72:
            return "THESIS_BELOW_72"
        if row.get("financial_check") != "PASS_SURVIVAL":
            return "CASH_EARNINGS_FAIL"
        margin = pd.to_numeric(row.get("dcf_margin_of_safety"), errors="coerce")
        if row.get("valuation_gate") not in {"REASONABLE", "FAIR_TO_RICH"} or pd.isna(margin) or margin < 0:
            return "VALUE_UNSUPPORTED"
        if row.get("timing_status") not in {"BOTTOM_HOLD_NO_ADD", "BOTTOM_VOLUME_CONFIRMATION"}:
            return "TIMING_NOT_READY"
        if row.get("evidence_status") not in {"SEED_READY", "SEED_READY_WITH_CAUTION"}:
            return "EVIDENCE_NOT_READY"
        return "OTHER_GATE_FAILED"

    out["first_failed_gate"] = out.apply(first_gate, axis=1)
    return out.sort_values(
        ["research_sequence", "barbell_state", "future_thesis_score", "ts_code"],
        ascending=[True, True, False, True],
    )


def update_valuation_warning_history(
    states: pd.DataFrame, previous_warnings: pd.DataFrame, as_of: str, destination: Path,
) -> pd.DataFrame:
    """Persist the latest seed valuation warning state for T+1 confirmation."""
    prior = {}
    if previous_warnings is not None and not previous_warnings.empty and "ts_code" in previous_warnings:
        frame = previous_warnings.copy()
        frame["ts_code"] = frame["ts_code"].astype(str)
        frame["warning_date"] = frame["warning_date"].astype(str) if "warning_date" in frame else ""
        prior = frame.drop_duplicates("ts_code", keep="last").set_index("ts_code").to_dict("index")
    rows = []
    for _, row in states.iterrows():
        code = str(row["ts_code"])
        status = str(row.get("valuation_warning_status", "NONE"))
        previous = prior.get(code, {})
        previous_status = str(previous.get("status", ""))
        previous_date = str(previous.get("warning_date", ""))
        if status == "WARNING":
            consecutive = int(previous.get("consecutive_days", 0)) + 1 if previous_status == "WARNING" and previous_date < as_of else 1
            warning_date = as_of if consecutive == 1 else previous_date
        elif status == "EXIT_DUE":
            consecutive = max(int(previous.get("consecutive_days", 1)) + 1, 2)
            warning_date = previous_date or as_of
        else:
            consecutive = 0
            warning_date = ""
            status = "CLEARED" if previous_status in {"WARNING", "EXIT_DUE"} else "NONE"
        rows.append({
            "ts_code": code, "name": row.get("name", ""), "as_of_date": as_of,
            "warning_date": warning_date, "consecutive_days": consecutive,
            "status": status, "dcf_margin_of_safety": row.get("dcf_margin_of_safety"),
            "valuation_premium_cap": row.get("valuation_premium_cap"),
            "reason": row.get("valuation_warning_reason", ""),
        })
    result = pd.DataFrame(rows)
    result.to_csv(destination, index=False, encoding="utf-8-sig")
    return result


def update_anchor_valuation_warning_history(
    anchors: pd.DataFrame,
    previous_warnings: pd.DataFrame,
    as_of: str,
    destination: Path,
    portfolio: pd.DataFrame | None = None,
    previous_portfolio: pd.DataFrame | None = None,
    cooldown_sessions: int = 5,
) -> pd.DataFrame:
    """Persist one-session warnings for anchors priced above the optimistic DCF."""
    prior = {}
    if previous_warnings is not None and not previous_warnings.empty and "ts_code" in previous_warnings:
        frame = previous_warnings.copy()
        frame["ts_code"] = frame["ts_code"].astype(str)
        frame["warning_date"] = frame["warning_date"].astype(str) if "warning_date" in frame else ""
        prior = frame.drop_duplicates("ts_code", keep="last").set_index("ts_code").to_dict("index")
    rows = []
    current_weights = {}
    previous_weights = {}
    if portfolio is not None and not portfolio.empty and "ts_code" in portfolio:
        current_weights = portfolio.set_index(portfolio["ts_code"].astype(str))["target_weight"].astype(float).to_dict()
    if previous_portfolio is not None and not previous_portfolio.empty and "ts_code" in previous_portfolio:
        previous_weights = previous_portfolio.set_index(previous_portfolio["ts_code"].astype(str))["target_weight"].astype(float).to_dict()
    for _, row in anchors.iterrows():
        code = str(row["ts_code"])
        previous = prior.get(code, {})
        previous_status = str(previous.get("status", ""))
        previous_date = str(previous.get("warning_date", ""))
        over_optimistic = str(row.get("anchor_dcf_status", "NOT_FETCHED")) == "OVER_OPTIMISTIC"
        previous_cooldown = int(float(previous.get("cooldown_sessions_remaining", 0) or 0))
        previous_reductions = int(float(previous.get("reduction_count", 0) or 0))
        last_reduction_date = str(previous.get("last_reduction_date", ""))
        reduced_now = (
            code in current_weights and code in previous_weights
            and current_weights[code] < previous_weights[code] - 1e-12
        )
        if over_optimistic:
            consecutive = int(previous.get("consecutive_days", 0)) + 1 if previous_status == "WARNING" and previous_date < as_of else 1
            warning_date = as_of if consecutive == 1 else previous_date
            status = "WARNING"
            if reduced_now:
                last_reduction_date = as_of
                previous_cooldown = cooldown_sessions
                previous_reductions += 1
            elif not last_reduction_date and consecutive >= 2:
                # Migration for the pre-cooldown ledger: the old repeated
                # reductions are treated as one already-confirmed reduction.
                last_reduction_date = as_of
                previous_cooldown = max(previous_cooldown, cooldown_sessions)
                previous_reductions = max(previous_reductions, 1)
            elif previous_date < as_of and previous_cooldown > 0:
                previous_cooldown -= 1
        else:
            consecutive = 0
            warning_date = ""
            status = "CLEARED" if previous_status == "WARNING" else "NONE"
            previous_cooldown = 0
            previous_reductions = 0
            last_reduction_date = ""
        rows.append({
            "ts_code": code,
            "name": row.get("name", ""),
            "as_of_date": as_of,
            "warning_date": warning_date,
            "consecutive_days": consecutive,
            "status": status,
            "anchor_dcf_status": row.get("anchor_dcf_status", "NOT_FETCHED"),
            "dcf_base_margin_of_safety": row.get("dcf_base_margin_of_safety"),
            "dcf_optimistic_margin_of_safety": row.get("dcf_optimistic_margin_of_safety"),
            "financial_as_of": row.get("financial_as_of", ""),
            "cooldown_sessions_remaining": max(previous_cooldown, 0),
            "reduction_count": previous_reductions,
            "last_reduction_date": last_reduction_date,
            "last_reduction_dcf_optimistic_margin": (
                row.get("dcf_optimistic_margin_of_safety") if reduced_now or (
                    last_reduction_date == as_of and not previous.get("last_reduction_date")
                ) else previous.get("last_reduction_dcf_optimistic_margin", "")
            ),
            "last_reduction_normalized_owner_earnings": (
                row.get("normalized_owner_earnings") if reduced_now or (
                    last_reduction_date == as_of and not previous.get("last_reduction_date")
                ) else previous.get("last_reduction_normalized_owner_earnings", "")
            ),
            "last_reduction_normalized_fcf": (
                row.get("normalized_fcf") if reduced_now or (
                    last_reduction_date == as_of and not previous.get("last_reduction_date")
                ) else previous.get("last_reduction_normalized_fcf", "")
            ),
        })
    result = pd.DataFrame(rows)
    result.to_csv(destination, index=False, encoding="utf-8-sig")
    return result


def write_report(portfolio: pd.DataFrame, states: pd.DataFrame, anchors: pd.DataFrame,
                 summary: dict, as_of: str, policy: dict) -> None:
    allocated = markdown_table(
        portfolio,
        ["name", "theme", "strategy_state", "target_weight", "reason"],
        ["公司", "主题", "状态", "目标权重", "原因"],
    )
    anchor_codes = set(
        portfolio.loc[portfolio["allocation_bucket"].eq("ANCHOR"), "ts_code"].astype(str)
    )
    seeds = states[
        states["barbell_state"].eq("OPTION_SEED")
        & ~states["ts_code"].astype(str).isin(anchor_codes)
    ]
    seed_table = markdown_table(
        seeds,
        ["name", "chain_segment", "future_thesis_score", "dcf_margin_of_safety", "timing_status", "barbell_state"],
        ["公司", "利润池环节", "未来逻辑分", "保守DCF安全边际", "择时", "策略状态"],
    )
    promoted = states[states["barbell_state"].isin(["CONFIRMED_BUILD", "PROMOTED_CORE"])]
    promoted_table = markdown_table(
        promoted,
        ["name", "theme", "future_thesis_score", "timing_status", "barbell_state"],
        ["公司", "主题", "未来逻辑分", "择时", "策略状态"],
    )
    evidence_view = states[
        states["evidence_status"].isin({"SEED_READY", "SEED_READY_WITH_CAUTION"})
    ].sort_values("future_thesis_score", ascending=False)
    evidence_table = markdown_table(
        evidence_view,
        ["name", "research_direction", "evidence_status", "supported_evidence_types",
         "caution_evidence_count", "barbell_state"],
        ["公司", "研究顺序", "证据状态", "已具备证据", "风险证据数", "组合状态"],
    )
    funnel_table = markdown_table(
        states.head(20),
        ["research_sequence", "research_direction", "name", "future_thesis_score",
         "dcf_margin_of_safety", "timing_status", "first_failed_gate"],
        ["顺序", "方向", "公司", "未来逻辑分", "DCF安全边际", "择时", "首个未通过门"],
    )
    policy_table = markdown_table(
        states.sort_values("policy_alignment_score", ascending=False).head(20),
        ["name", "policy_name", "policy_status", "policy_alignment_score", "mapping_evidence_required"],
        ["公司", "国家规划方向", "政策门", "政策对齐分", "仍需核实的公司证据"],
    )
    pending_anchors = anchors.head(30)
    anchor_table = markdown_table(
        pending_anchors,
        ["name", "l3_name", "subindustry_market_cap_rank", "economic_factor", "moat_proxy_type",
         "moat_proxy_score", "revenue_cagr", "normalized_gross_margin", "normalized_fcf_conversion",
         "dividend_payout_proxy", "anchor_score", "defensive_status"],
        ["公司", "细分行业", "市值位次", "经济因子", "护城河代理", "代理分", "收入CAGR",
         "三年毛利率中位数", "FCF/所有者收益", "分红覆盖代理", "自动锚分", "状态"],
    )
    report = f"""# 前瞻哑铃投资策略

数据日期：{as_of}

## 当前组合结论

- 稳定现金流锚：{summary['anchor_weight']:.1%}
- 未来产业仓：{summary['future_weight']:.1%}
- 其中种子仓：{summary['option_seed_weight']:.1%}（目标 {summary['option_seed_target_min']:.1%}—{summary['option_seed_total_cap']:.1%}，状态 `{summary['option_seed_target_status']}`）
- 其中确认加仓：{summary['confirmed_build_weight']:.1%}
- 其中核心仓：{summary['promoted_core_weight']:.1%}
- 现金：{summary['cash_weight']:.1%}
- 尚未分配的锚仓预算：{summary['anchor_unallocated']:.1%}
- 全A股扫描：{int(summary['anchor_universe_scanned'])}只
- 财务复核：{int(summary['anchor_financial_reviewed'])}只
- 财务数据完整：{int(summary['anchor_financial_complete'])}只
- 护城河代理与财务门合格：{int(summary['anchor_eligible'])}只

锚仓先通过全A股财务门，再要求细分行业市值位次与“品牌溢价/规模成本领先”代理同时成立。长期毛利率、ROE、收入韧性和现金转化用于验证溢价是否真的转化为利润；高股息本身不再视为护城河。代理只能缩小研究范围，不能证明消费者心智、独占资源或真实市场份额，因此当前组合中的锚仓统一标记为 `PROXY_REQUIRES_PRIMARY_EVIDENCE`。

新锚仓必须通过10%基准DCF安全边际。已有锚仓若基准估值略高但仍处于乐观DCF情景内，会保留原仓位并暂停加仓；若连续高于乐观情景，先预警一个交易日，再按2.5个百分点减仓，估值本身不直接清仓。

未来产业候选还必须通过国家规划门。政策方向来自正式《十五五规划纲要》；“六张网”是依据第七章派生的统一研究口径，并非原文中的固定总称。

## 当前目标仓位

{allocated}

## 小额未来期权仓

{seed_table}

`OPTION_SEED` 每家公司目标权重为 {float(policy['option_seed_weight']):.1%}，总种子仓控制在 {float(policy['option_seed_target_min']):.1%}—{float(policy['option_seed_total_cap']):.1%}。它要求未来逻辑、最低可审计证据、现金收益和保守估值均通过并位于底部；`CAUTION` 风险证据不会自动否决小额试错仓，但在解决前禁止升级核心仓。

## 种子仓证据结果

{evidence_table}

证据状态只决定是否允许小额试错。`SEED_READY_WITH_CAUTION` 表示已经记录了明确负面事实，仍可保留2.5%，但不能升级核心仓。

## 按方向自动筛选结果

{funnel_table}

系统只对通过前序政策、逻辑、财务、估值和底部门的公司开展深度证据核验，避免把研究时间花在当前价格已经不支持或现金收益尚未成立的公司上。

## 国家规划对齐池

{policy_table}

国家规划只决定研究范围。公司必须证明其收入直接暴露于规划方向，而且利润池没有被低价招标、过度扩产、客户议价或高资本开支侵蚀；否则仍是 `POLICY_WATCH` 或 `RESEARCH_ONLY`。

## 已确认加仓与核心仓

{promoted_table}

至少两个里程碑确认后进入 `CONFIRMED_BUILD`，仓位为 {float(policy['confirmed_build_weight']):.1%}；三个里程碑全部 `VERIFIED`、没有未解决风险证据并出现底部放量趋势后，进入 `PROMOTED_CORE`，仓位为 {float(policy['promoted_core_weight']):.1%}。证据退化会按相同阶梯降回5%、2.5%或0%。

## 稳定锚自动筛选

{anchor_table}

系统先扫描全部在市A股，再按上市年限、ST/退市风险、规模、股息、PE/PB及行业模型适用性建立财务短名单。银行、非银金融、公用事业、电信运营商和强周期资源行业不套用本工业公司模型。自动锚除原有所有者收益、ROE、FCF、负债和估值门外，还要求：收入长期复合增速不低于-3%、毛利率波动不高于0.15、最新毛利率相对三年中位数下滑不超过3个百分点、FCF/所有者收益不低于0.50、分红/所有者收益不高于1.10、细分行业市值位次不低于前三，并通过品牌溢价或规模成本领先代理。单家公司不超过15%，单一申万行业和单一经济因子均不超过20%，最多6家公司。上表只展示得分最高的30家公司，完整结果保存在CSV中。

### 锚仓调仓纪律

正常运行继承上一交易日已经公布的锚仓名称和仓位；每日评分的小幅变化不能替换既有锚仓。筛选状态需要复核时，只按 {float(policy.get('anchor_reduction_step', 0.025)):.1%} 的阶梯减仓，最低保留 {float(policy.get('anchor_min_weight', 0.025)):.1%}，不自动清仓。若价格连续高于乐观DCF，先预警、确认后只减一档，随后至少冷静 {int(policy.get('anchor_valuation_cooldown_sessions', 5))} 个交易日；再次减仓还必须出现新的财务/业绩或DCF恶化证据。新锚仓只有在现金和名额都充足时，才以 {float(policy.get('anchor_entry_weight', 0.025)):.1%} 观察仓进入，不得挤出既有锚仓。本轮没有使用宏观大环境择时信号；调仓只由个股门槛/证据状态、分散约束和现金预算驱动。

## 策略结构

1. 稳定锚目标上限为 {float(policy['anchor_target']):.0%}，负责现金流、分红和等待时间。
2. 未验证的未来公司仓位为零；通过底部价值检查后，每家公司只给 {float(policy['option_seed_weight']):.1%} 期权仓。
3. 至少两个产业里程碑确认后升级到 {float(policy['confirmed_build_weight']):.1%}；三层证据与趋势全部确认后升级到 {float(policy['promoted_core_weight']):.1%}。证据转弱时按相同阶梯减仓。
4. 未来产业总仓不超过 {float(policy['future_total_cap']):.0%}，单一主题不超过 {float(policy['single_theme_cap']):.0%}，现金至少保留 {float(policy['cash_floor']):.0%}。
5. 任一证伪条件触发，状态直接变为 `INVALIDATED`，目标仓位归零。

## 这套策略如何验证

不以历史回测收益或Sharpe作为准入标准。从今天开始保存每次产业判断、证据日期、来源、里程碑状态和目标仓位，使用真实的前向记录检查判断质量。价格数据只负责底部和加仓时机，不负责决定产业未来。

本报告是研究规则输出，不是自动交易指令。下单前仍需复核公告、财务数据、流动性和个人风险承受能力。
"""
    (OUT / "README.md").write_text(report, encoding="utf-8")


def write_policy_report(states: pd.DataFrame, priorities: pd.DataFrame, as_of: str) -> None:
    POLICY_OUT.mkdir(parents=True, exist_ok=True)
    priority_view = priorities[["policy_name", "official_chapter", "official_wording", "classification_note"]].copy()
    priority_view.columns = ["统一方向", "规划位置", "规划原文方向", "口径说明"]
    candidate_view = states.sort_values("policy_alignment_score", ascending=False)[
        ["name", "policy_name", "policy_status", "policy_alignment_score", "valuation_gate",
         "dcf_margin_of_safety", "timing_status", "barbell_state"]
    ].copy()
    candidate_view["policy_alignment_score"] = candidate_view["policy_alignment_score"].round(1)
    candidate_view["dcf_margin_of_safety"] = pd.to_numeric(candidate_view["dcf_margin_of_safety"], errors="coerce").map(
        lambda x: "—" if pd.isna(x) else f"{x:.1%}"
    )
    candidate_view.columns = ["公司", "国家规划方向", "政策门", "政策对齐分", "估值约束", "DCF安全边际", "择时", "组合状态"]
    report = f"""# 十五五国家规划驱动投资框架

数据日期：{as_of}

政策来源：[《中华人民共和国国民经济和社会发展第十五个五年规划纲要》](https://www.gov.cn/yaowen/liebiao/202603/content_7062633.htm)，2026年3月13日发布。

## 统一政策方向

{priority_view.to_markdown(index=False)}

正式纲要没有使用“六张网”这一固定总称。本项目根据第七章的原文结构，把综合交通、新型能源、现代水网以及新型基础设施中的通信、算力、民用空间拆成六个可重复使用的研究网络；智能网联汽车、机器人、具身智能、集成电路和高端仪器沿用纲要的产业原文口径。

## 当前政策候选池

{candidate_view.to_markdown(index=False)}

## 机械化决策顺序

1. 只有国家级正式规划和政府原文映射可以进入政策池。
2. 公司必须证明业务直接暴露于规划方向；概念关联不足以通过。
3. 政策明确但利润池弱、过度扩产或项目回款差，只能观察。
4. 通过政策门后，继续执行现金收益、保守估值和底部择时门。
5. 需求、利润池和公司兑现三类里程碑全部具备带日期来源的证据，且底部放量确认后，才允许升级核心仓。
6. 任一证伪条件触发，目标仓位归零。

国家规划减少了“张三看好什么、李四看好什么”的方向偏差，但不能消除公司映射和利润池判断。系统通过固定字段、阈值、证据来源与状态机，使不同使用者面对相同证据时得到相同结果。
"""
    (POLICY_OUT / "README.md").write_text(report, encoding="utf-8")
    states.to_csv(POLICY_OUT / "policy_candidates.csv", index=False, encoding="utf-8-sig")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh-financials", action="store_true", help="refresh anchor financial statements from Tushare")
    parser.add_argument("--offline", action="store_true", help="use cached statements only; do not fetch missing files")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    POLICY_OUT.mkdir(parents=True, exist_ok=True)
    policy = yaml.safe_load(Path("config/barbell-policy.yaml").read_text(encoding="utf-8"))
    future = pd.read_csv("outputs/future-demand-screen/future_demand_candidates.csv")
    daily = pd.read_csv("data/processed/portfolio/daily_basic_latest.csv")
    policy_mapping = pd.read_csv("config/policy-candidate-map.csv")
    policy_priorities = pd.read_csv("config/policy-priorities.csv")
    future = apply_policy_alignment(future, policy_mapping, policy_priorities)
    future.to_csv(OUT / "policy_aligned_candidates.csv", index=False, encoding="utf-8-sig")
    milestones = pd.read_csv("config/future-milestones.csv")
    registry = pd.read_csv("config/future-thesis-registry.csv")
    evidence = pd.read_csv("config/future-evidence-ledger.csv")
    as_of_raw = str(int(pd.to_numeric(daily["trade_date"], errors="coerce").max()))
    as_of = f"{as_of_raw[:4]}-{as_of_raw[4:6]}-{as_of_raw[6:]}"
    previous_portfolio = pd.DataFrame()
    holdings_history = OUT / "portfolio_holdings_history.csv"
    if holdings_history.exists():
        history = pd.read_csv(holdings_history)
        if not history.empty and "date" in history and "ts_code" in history:
            history["date"] = history["date"].astype(str)
            prior_dates = sorted(date for date in history["date"].unique() if date < as_of)
            if prior_dates:
                previous_portfolio = history[history["date"].eq(prior_dates[-1])].copy()
    warning_path = OUT / "future_valuation_warnings.csv"
    previous_warnings = pd.read_csv(warning_path) if warning_path.exists() else pd.DataFrame()
    anchor_warning_path = OUT / "anchor_valuation_warnings.csv"
    previous_anchor_warnings = pd.read_csv(anchor_warning_path) if anchor_warning_path.exists() else pd.DataFrame()
    evidence_readiness = build_evidence_readiness(registry, evidence, as_of)
    evidence_readiness.to_csv(OUT / "future_evidence_readiness.csv", index=False, encoding="utf-8-sig")
    states = classify_future_states(
        future, milestones, evidence_readiness,
        previous_portfolio=previous_portfolio,
        valuation_warnings=previous_warnings,
        as_of=as_of,
        policy=policy,
    )
    states = build_future_research_funnel(states)
    update_valuation_warning_history(states, previous_warnings, as_of, warning_path)
    states.to_csv(OUT / "future_states.csv", index=False, encoding="utf-8-sig")
    states.to_csv(OUT / "future_seed_research_funnel.csv", index=False, encoding="utf-8-sig")

    members = pd.read_csv("data/processed/metadata/sw2021_members.csv")
    security_master = pd.read_csv("data/processed/metadata/security_master.csv")
    anchor_funnel, watchlist = build_full_market_anchor_universe(daily, security_master, members, policy)
    anchor_funnel.to_csv(OUT / "full_market_anchor_funnel.csv", index=False, encoding="utf-8-sig")
    daily = daily.merge(members[["ts_code", "l1_name"]].drop_duplicates("ts_code"), on="ts_code", how="left")
    anchor_financials = anchor_financial_checks(
        watchlist, daily, args.refresh_financials, fetch_missing=not args.offline,
        discount_rate=float(policy.get("dcf_base_discount_rate", 0.10)),
        discount_rate_step=float(policy.get("dcf_sensitivity_step", 0.01)),
    )
    anchors = anchor_signal_table(daily, watchlist, anchor_financials, policy)
    anchors.to_csv(OUT / "anchor_screen.csv", index=False, encoding="utf-8-sig")
    portfolio, summary = build_barbell_weights(
        anchors,
        states,
        policy,
        previous_portfolio=previous_portfolio,
        anchor_valuation_warnings=previous_anchor_warnings,
        as_of=as_of,
    )
    update_anchor_valuation_warning_history(
        anchors, previous_anchor_warnings, as_of, anchor_warning_path,
        portfolio=portfolio, previous_portfolio=previous_portfolio,
        cooldown_sessions=int(policy.get("anchor_valuation_cooldown_sessions", 5)),
    )
    selected_anchor_codes = set(
        portfolio.loc[portfolio["allocation_bucket"].eq("ANCHOR"), "ts_code"].astype(str)
    )
    moat_review = anchors[anchors["defensive_status"].eq("DEFENSIVE_ELIGIBLE")].copy()
    moat_review["selected_anchor"] = moat_review["ts_code"].astype(str).isin(selected_anchor_codes)
    moat_review["primary_evidence_status"] = "PRIMARY_EVIDENCE_REQUIRED"
    moat_review["required_primary_evidence"] = (
        "annual report or authoritative industry source: market-share/rank; persistent price premium or cost advantage; "
        "brand/resource/network/switching-cost mechanism; dated invalidation trigger"
    )
    moat_review = moat_review.sort_values(
        ["selected_anchor", "anchor_score", "ts_code"], ascending=[False, False, True]
    )
    moat_review.to_csv(OUT / "anchor_moat_review_queue.csv", index=False, encoding="utf-8-sig")
    summary.update({
        "anchor_universe_scanned": len(anchor_funnel),
        "anchor_financial_reviewed": len(anchors),
        "anchor_financial_complete": int(anchors["anchor_financial_check"].ne("NOT_FETCHED").sum()),
        "anchor_eligible": int(anchors["defensive_status"].eq("DEFENSIVE_ELIGIBLE").sum()),
    })
    portfolio.to_csv(OUT / "target_portfolio.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([{"as_of_date": as_of, **summary, "backtest_gate": "NOT_USED"}]).to_csv(
        OUT / "portfolio_summary.csv", index=False, encoding="utf-8-sig"
    )
    write_report(portfolio, states, anchors, summary, as_of, policy)
    write_policy_report(states, policy_priorities, as_of)
    update_portfolio_nav_history(OUT, daily)
    site_public = PROJECT_ROOT / "portfolio-site" / "public" / "data" / "portfolio.json"
    if site_public.parent.parent.parent.exists():
        export_portfolio_site_data(OUT, site_public)
    print(pd.DataFrame([{"as_of_date": as_of, **summary, "backtest_gate": "NOT_USED"}]).to_string(index=False))
    print("\nTarget portfolio:")
    print(portfolio.to_string(index=False) if not portfolio.empty else "No allocated securities; budget remains cash.")
    print(f"\nSaved to {OUT}")


if __name__ == "__main__":
    main()
