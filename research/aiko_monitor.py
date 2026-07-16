"""A point-in-time monitor: thesis evidence first, price confirmation second."""
from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd

PEERS = ["600438.SH", "601012.SH", "002459.SZ", "002129.SZ", "002865.SZ", "688223.SH"]

def _read_ledger(path: Path, as_of: pd.Timestamp, date_column: str) -> pd.DataFrame:
    data = pd.read_csv(path, comment="#")
    if data.empty:
        return data
    data[date_column] = pd.to_datetime(data[date_column], errors="coerce")
    return data[data[date_column] <= as_of].sort_values(date_column)

def market_snapshot(stock: pd.DataFrame, basic: pd.DataFrame, flow: pd.DataFrame, peers: pd.DataFrame) -> dict[str, float | str | bool]:
    data = stock.sort_index(); date = data.index[-1]; close = data.close
    peer_return = peers.pct_change().mean(axis=1).reindex(data.index)
    net_flow_ratio = (flow.net_mf_amount / data.amount.replace(0, np.nan)).reindex(data.index)
    basic = basic.reindex(data.index)
    sma20, sma60 = close.rolling(20).mean().iloc[-1], close.rolling(60).mean().iloc[-1]
    return {
        "as_of": date.date().isoformat(), "close": float(close.iloc[-1]),
        "above_sma20": bool(close.iloc[-1] > sma20), "above_sma60": bool(close.iloc[-1] > sma60),
        "relative_return_20d": float(close.pct_change(20).iloc[-1] - peer_return.rolling(20).sum().iloc[-1]),
        "relative_return_60d": float(close.pct_change(60).iloc[-1] - peer_return.rolling(60).sum().iloc[-1]),
        "net_flow_5d": float(net_flow_ratio.rolling(5).sum().iloc[-1]),
        "turnover_rate": float(basic.turnover_rate.iloc[-1]), "pb": float(basic.pb.iloc[-1]),
        "pb_zscore_252d": float(((basic.pb-basic.pb.rolling(252).mean()) / basic.pb.rolling(252).std()).iloc[-1]),
    }

def evidence_table(kpis: pd.DataFrame, industry: pd.DataFrame) -> str:
    if kpis.empty and industry.empty:
        return "尚未录入带发布日期的经营或行业数据；不能据此判断基本面是否兑现。"
    lines = []
    for label, df, date in [("公司经营", kpis, "announcement_date"), ("行业", industry, "release_date")]:
        if not df.empty:
            recent = df.groupby("metric", as_index=False).tail(1)
            rows = "\n".join(f"| {r.metric} | {r.value} {r.unit} | {r[date].date()} | {r.source} | {r.note} |" for _, r in recent.iterrows())
            lines.append(f"### {label}\n\n| 指标 | 数值 | 信息日期 | 来源 | 状态/备注 |\n| --- | ---: | --- | --- | --- |\n{rows}")
    return "\n".join(lines)

def latest_income(income: pd.DataFrame, as_of: pd.Timestamp) -> str:
    if income.empty: return "未取得财务报表数据。"
    announce = income.get("f_ann_date", income.get("ann_date"))
    eligible = income[announce <= as_of].copy() if announce is not None else income
    if eligible.empty: return "截至信号日没有已披露财务报表。"
    row = eligible.sort_values(["end_date", "f_ann_date" if "f_ann_date" in eligible else "ann_date"]).iloc[-1]
    rev = row.get("revenue", row.get("total_revenue", np.nan)); profit = row.get("n_income_attr_p", np.nan)
    return f"最近可用报告期：{row.get('end_date').date()}；营业收入 {rev:,.0f}，归母净利润 {profit:,.0f}（Tushare 原始口径，单位以报表为准）。"

def make_report(snapshot: dict, kpis: pd.DataFrame, industry: pd.DataFrame, income: pd.DataFrame) -> str:
    technical = sum([snapshot["above_sma20"], snapshot["above_sma60"], snapshot["relative_return_20d"] > 0, snapshot["net_flow_5d"] > 0])
    trigger = "确认偏强" if technical >= 3 else "等待确认" if technical == 2 else "未确认"
    return f"""# 爱旭股份基本面—行业—价格监控

数据截至 **{snapshot['as_of']}**。本文件是研究监控，不是交易指令；基本面与行业证据优先，K 线只用于确认市场是否开始交易该逻辑。

## 1. 基本面兑现证据

{evidence_table(kpis, industry)}

{latest_income(income, pd.Timestamp(snapshot['as_of']))}

## 2. 市场定价与 K 线确认

| 指标 | 当前值 |
| --- | ---: |
| 收盘价 | {snapshot['close']:.2f} |
| 位于 20 日均线上方 | {'是' if snapshot['above_sma20'] else '否'} |
| 位于 60 日均线上方 | {'是' if snapshot['above_sma60'] else '否'} |
| 相对光伏同业 20 日收益 | {snapshot['relative_return_20d']:.1%} |
| 相对光伏同业 60 日收益 | {snapshot['relative_return_60d']:.1%} |
| 5 日资金净流入 / 成交额 | {snapshot['net_flow_5d']:.1%} |
| 换手率 | {snapshot['turnover_rate']:.2f}% |
| PB | {snapshot['pb']:.2f} |
| PB 相对 252 日 Z 分数 | {snapshot['pb_zscore_252d']:.2f} |

**技术确认状态：{trigger}**（4 项中 {technical} 项为正）。这不是对未来涨跌的概率预测。

## 3. 更新纪律

1. 每次公司公告或业绩交流后，在 `config/aiko_operating_kpis.csv` 新增一行，并填真实发布日期与来源。
2. 每周在 `config/aiko_industry_weekly.csv` 更新至少一项行业数据；只使用公布日已知的数值。
3. 只有“经营指标改善 + 行业条件不恶化 + 技术确认”同时出现时，才将研究状态从观察提升为进一步核查；任何一项缺失均保持不确定。
"""
