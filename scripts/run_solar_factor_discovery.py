#!/usr/bin/env python3
"""Compare sector-aware factors/models for 600732.SH."""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from data_loader.tushare_client import TushareClient
from research.solar_factor_discovery import FEATURES, build_frame, evaluate

START, END, STOCK = "20180101", "20260710", "600732.SH"
PEERS = ["600438.SH", "601012.SH", "002459.SZ", "002129.SZ", "002865.SZ", "688223.SH"]
def main():
    c=TushareClient(data_dir=ROOT/"data/raw")
    stock=c.stock_daily(STOCK,START,END); basic=c.daily_basic(STOCK,START,END); flow=c.moneyflow(STOCK,START,END)
    market=c.index_daily("000300.SH",START,END)
    peers=pd.concat({code:c.stock_daily(code,START,END).close for code in PEERS},axis=1, sort=True)
    frame=build_frame(stock,basic,flow,market.close,peers)
    folds, models=evaluate(frame)
    means=folds.groupby("model")[["roc_auc","balanced_accuracy"]].mean().sort_values("roc_auc",ascending=False)
    best=means.index[0]; latest=frame.iloc[-1:]; prob=models[best].predict_proba(latest[FEATURES])[:,1][0]
    out=ROOT/"outputs/solar-factor-discovery"; out.mkdir(parents=True,exist_ok=True)
    folds.to_csv(out/"model_folds.csv",index=False); means.to_csv(out/"model_summary.csv")
    selected=list(pd.Index(FEATURES)[models[best].named_steps["select"].get_support()])
    comparison = "\n".join(f"| {name} | {row.roc_auc:.3f} | {row.balanced_accuracy:.3f} |" for name, row in means.iterrows())
    text=f"""# 爱旭股份行业因子发现\n\n截至 {latest.index[0].date()}，目标仍为未来 20 个交易日上涨超过 8%。候选因子覆盖：光伏同业相对强弱、相对沪深300强弱、PB 均值回归、换手率/量比及大单/总体资金流。\n\n| 模型 | 样本外 ROC-AUC | 平衡准确率 |\n| --- | ---: | ---: |\n{comparison}\n\n最佳模型为 **{best}**，最新概率为 **{prob:.1%}**。当前模型选中的因子：{', '.join(selected)}。\n\n{'验证通过，可作为低频研究信号。' if means.loc[best,'roc_auc'] > .55 and means.loc[best,'balanced_accuracy'] > .52 else '未验证通过：即使加入行业、估值和资金流因子，样本外表现仍不足以作为预测或交易依据。'}\n"""
    (out/"README.md").write_text(text,encoding="utf-8"); print(text)
if __name__ == "__main__": main()
