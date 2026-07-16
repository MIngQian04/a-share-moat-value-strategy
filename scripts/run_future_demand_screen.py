"""Rank future-demand profit pools, then apply valuation and timing constraints."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_loader.tushare_client import TushareClient
from selection.future_demand import decision_status, research_tier, score_future_thesis, valuation_gate
from valuation.owner_earnings import owner_earnings_from_statements


OUT = Path("outputs/future-demand-screen")
FIN = Path("data/raw/fundamental")


def timing_features(close: pd.DataFrame, volume: pd.DataFrame, codes: list[str]) -> pd.DataFrame:
    rows = []
    for code in codes:
        if code not in close or code not in volume:
            continue
        px = pd.to_numeric(close[code], errors="coerce").dropna()
        vol = pd.to_numeric(volume[code], errors="coerce").reindex(px.index).dropna()
        if len(px) < 252 or len(vol) < 60:
            continue
        p252 = px.iloc[-252:]
        position = (px.iloc[-1] - p252.min()) / (p252.max() - p252.min()) if p252.max() > p252.min() else 0.5
        above20 = px.iloc[-1] >= px.iloc[-20:].mean()
        above60 = px.iloc[-1] >= px.iloc[-60:].mean()
        volume_ratio = vol.iloc[-20:].mean() / vol.iloc[-60:].mean() if vol.iloc[-60:].mean() > 0 else np.nan
        return20 = px.iloc[-1] / px.iloc[-21] - 1
        if position <= 0.40 and above20 and above60 and volume_ratio >= 1.15 and return20 > 0:
            status = "BOTTOM_VOLUME_CONFIRMATION"
        elif position <= 0.35:
            status = "BOTTOM_HOLD_NO_ADD"
        elif above20 and above60 and volume_ratio >= 1.15:
            status = "TREND_CONFIRMED_NOT_BOTTOM"
        else:
            status = "WAIT_NO_CONFIRMATION"
        rows.append({
            "ts_code": code,
            "price_position_252": position,
            "above_ma20": above20,
            "above_ma60": above60,
            "volume_20_to_60": volume_ratio,
            "return_20d": return20,
            "timing_status": status,
        })
    return pd.DataFrame(rows)


def get_statements(client: TushareClient | None, code: str, refresh: bool) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    frames = []
    for endpoint in ["income", "cashflow", "balancesheet"]:
        path = FIN / endpoint / f"{code.replace('.', '_')}.parquet"
        if path.exists() and not refresh:
            frame = pd.read_parquet(path)
        elif client is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            frame = getattr(client.pro, endpoint)(ts_code=code, start_date="20190101")
            frame = pd.DataFrame() if frame is None else frame
            frame.to_parquet(path, index=False)
            time.sleep(client.sleep_seconds)
        else:
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        frames.append(frame)
    return tuple(frames)


def financial_checks(screen: pd.DataFrame, refresh: bool) -> pd.DataFrame:
    client = TushareClient(data_dir="data/raw") if refresh else None
    rows = []
    for _, row in screen.iterrows():
        try:
            income, cashflow, balance = get_statements(client, row["ts_code"], refresh)
            if income.empty or cashflow.empty or balance.empty:
                rows.append({"ts_code": row["ts_code"], "financial_check": "NOT_FETCHED"})
                continue
            value = owner_earnings_from_statements(
                income, cashflow, balance, float(row["total_share"]) * 10000.0
            )
            market_cap = float(row["total_mv"]) * 10000.0
            owner_yield = value["normalized_owner_earnings"] / market_cap if market_cap > 0 else np.nan
            dcf_price = value["owner_earnings_value_per_share"]
            margin = dcf_price / float(row["close"]) - 1 if pd.notna(dcf_price) and row["close"] > 0 else np.nan
            check = "PASS_SURVIVAL" if value["normalized_owner_earnings"] > 0 and value["normalized_fcf"] > 0 else "FAIL_CASH_EARNINGS"
            rows.append({"ts_code": row["ts_code"], **value, "owner_earnings_yield": owner_yield,
                         "dcf_margin_of_safety": margin, "financial_check": check})
        except Exception as exc:
            rows.append({"ts_code": row["ts_code"], "financial_check": f"ERROR: {str(exc)[:120]}"})
    columns = ["ts_code", "financial_years", "normalized_owner_earnings", "normalized_fcf",
               "net_cash", "owner_earnings_value_per_share", "owner_earnings_yield",
               "dcf_margin_of_safety", "financial_check"]
    return pd.DataFrame(rows).reindex(columns=columns)


def write_report(result: pd.DataFrame, as_of: str) -> None:
    def table(frame: pd.DataFrame) -> str:
        if frame.empty:
            return "暂无。"
        cols = ["name", "chain_segment", "future_thesis_score", "close", "pe_ttm", "pb",
                "financial_check", "dcf_margin_of_safety", "timing_status", "key_risk"]
        shown = frame[cols].copy()
        shown["future_thesis_score"] = shown["future_thesis_score"].round(1)
        shown["close"] = shown["close"].round(2)
        shown["pe_ttm"] = shown["pe_ttm"].round(1)
        shown["pb"] = shown["pb"].round(1)
        shown["dcf_margin_of_safety"] = shown["dcf_margin_of_safety"].round(2)
        shown.columns = ["公司", "利润池环节", "未来逻辑分", "收盘价", "PE TTM", "PB", "现金收益检查", "保守DCF安全边际", "择时状态", "主要风险"]
        return shown.to_markdown(index=False)

    core = result[result["research_tier"].eq("CORE_RESEARCH")]
    optional = result[result["research_tier"].eq("OPTIONALITY_WATCH")]
    verified = result[result["decision_status"].isin(["MANUAL_ENTRY_REVIEW", "VALUE_VERIFIED_WAIT_TIMING"])]
    report = f"""# 未来需求—利润池筛选

数据日期：{as_of}

## 结论

这不是用历史利润外推未来的财务排名。第一层先问未来需求是否确定，第二层判断产业链哪个环节具有认证、工艺、客户切换成本或系统集成壁垒，第三层才用估值和现金收益检查是否值得继续研究。高分只代表研究优先级，不构成买入建议。

最重要的约束是：未来需求确定，不等于对应公司利润确定。竞争、技术替代、客户议价和资本开支都可能把行业增长吃掉。

## 估值通过、等待择时

{table(verified)}

这张表才是当前最接近可执行研究的名单；若择时仍是 `BOTTOM_HOLD_NO_ADD`，只代表位于低位观察区，不代表已经出现加仓信号。

## 核心研究池

{table(core)}

## 未来期权观察池

{table(optional)}

## 如何与低位建仓策略连接

- `BOTTOM_HOLD_NO_ADD`：可进入底部观察或极小仓研究阶段，但趋势没确认，不加仓。
- `BOTTOM_VOLUME_CONFIRMATION`：同时满足一年价格低位、20/60日均线转强和20日均量高于60日均量15%，才视为底部放量确认。
- `TREND_CONFIRMED_NOT_BOTTOM`：趋势已出现但不在低位，不能套用“底部建仓”逻辑，应重新评估赔率。
- `WAIT_NO_CONFIRMATION`：没有可执行的趋势信号。

## 评分边界

- 未来逻辑分来自人工研究假设（1—5分），重点是需求确定性、瓶颈强度、价值捕获和上市公司业务暴露；竞争与替代风险扣分。
- PE/PB/PS和所有者收益只作约束和否决项，不参与未来逻辑分，避免用滞后数据替代产业判断。
- DCF采用历史三年所有者收益中位数和保守增长率，只适合检验当前利润是否足以支撑价格，不能给尚未兑现的新业务定价。
- 公司业务映射和人工评分需要随年报、订单、客户结构及技术路线变化持续复核。

## 产业依据

- IEA《Energy and AI》指出数据中心与AI发展离不开电力，并评估未来十年的电力需求与供给结构：[IEA Energy and AI](https://www.iea.org/reports/energy-and-ai)。
- 美国NHTSA持续跟踪驾驶辅助和自动驾驶技术的测试、开发与验证，支持“物理感知—计算—控制”需求长期存在，但不能证明某一种传感器路线必胜：[NHTSA Automated Vehicles](https://www.nhtsa.gov/vehicle-safety/automated-vehicles-safety)。
"""
    (OUT / "README.md").write_text(report, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh-financials", action="store_true", help="download statements for every thesis candidate")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    hypotheses = pd.read_csv("config/future-demand-candidates.csv")
    hypotheses = score_future_thesis(hypotheses)
    members = pd.read_csv("data/processed/metadata/sw2021_members.csv")
    names = members[["ts_code", "name", "l1_name", "l2_name", "l3_name"]].drop_duplicates("ts_code")
    daily = pd.read_csv("data/processed/portfolio/daily_basic_latest.csv")
    close = pd.read_parquet("data/processed/research/close.parquet")
    volume = pd.read_parquet("data/processed/research/volume.parquet")
    timing = timing_features(close, volume, hypotheses["ts_code"].tolist())
    cycle_path = Path("outputs/sw-industry-value-screen/industry_cycle.csv")
    cycle = pd.read_csv(cycle_path)[["l1_name", "cycle_state", "cycle_score"]] if cycle_path.exists() else pd.DataFrame()

    result = hypotheses.merge(names, on="ts_code", how="left").merge(daily, on="ts_code", how="left")
    result = result.merge(timing, on="ts_code", how="left")
    if not cycle.empty:
        result = result.merge(cycle, on="l1_name", how="left")
    result["valuation_gate"] = valuation_gate(result)
    result["research_tier"] = research_tier(result)
    financial = financial_checks(result, args.refresh_financials)
    result = result.merge(financial, on="ts_code", how="left")
    result["decision_status"] = decision_status(result)
    order = pd.Categorical(result["research_tier"],
                           ["CORE_RESEARCH", "OPTIONALITY_WATCH", "SECONDARY_WATCH", "PASS_FOR_NOW"], ordered=True)
    result = result.assign(_order=order).sort_values(["_order", "future_thesis_score"], ascending=[True, False]).drop(columns="_order")
    result.to_csv(OUT / "future_demand_candidates.csv", index=False, encoding="utf-8-sig")
    as_of = str(int(pd.to_numeric(result["trade_date"], errors="coerce").max()))
    as_of = f"{as_of[:4]}-{as_of[4:6]}-{as_of[6:]}"
    write_report(result, as_of)
    print(result[["ts_code", "name", "chain_segment", "future_thesis_score", "valuation_gate",
                  "timing_status", "research_tier"]].to_string(index=False))
    print(f"\nSaved to {OUT}")


if __name__ == "__main__":
    main()
