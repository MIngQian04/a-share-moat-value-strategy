#!/usr/bin/env python3
"""Train and report a leakage-aware 20-session signal for one stock."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_loader.tushare_client import TushareClient
from research.single_stock_predictor import FEATURE_COLUMNS, HORIZON, THRESHOLD, build_dataset, fit_and_predict


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ts-code", default="600732.SH")
    parser.add_argument("--start-date", default="20180101")
    parser.add_argument("--end-date", default="20260710")
    parser.add_argument("--splits", type=int, default=5)
    args = parser.parse_args()
    root = ROOT
    client = TushareClient(data_dir=root / "data/raw")
    daily = client.stock_daily(args.ts_code, args.start_date, args.end_date)
    dataset = build_dataset(daily)
    result = fit_and_predict(dataset, n_splits=args.splits)
    output_dir = root / "outputs/single-stock-prediction"
    output_dir.mkdir(parents=True, exist_ok=True)
    result.folds.to_csv(output_dir / "walk_forward_folds.csv", index=False)
    latest = dataset.loc[result.latest_date]
    summary = pd.DataFrame([{
        "ts_code": args.ts_code,
        "as_of": result.latest_date.date().isoformat(),
        "horizon_trading_days": HORIZON,
        "target": f"future return > {THRESHOLD:.0%}",
        "probability": result.latest_probability,
        "signal": result.latest_signal,
        "selected_features": ", ".join(result.selected_features),
        "latest_close": latest["close"],
    }])
    summary.to_csv(output_dir / "latest_signal.csv", index=False)
    metrics = result.folds[["accuracy", "balanced_accuracy", "precision", "roc_auc"]].mean(numeric_only=True)
    validation = (
        "验证通过：信号在这段走步样本中显示出有限区分能力。"
        if metrics["roc_auc"] > 0.55 and metrics["balanced_accuracy"] > 0.52
        else "未验证通过：ROC-AUC 与平衡准确率未超过合理的随机基准；最新概率仅作模型输出，不应据此交易。"
    )
    report = f"""# {args.ts_code} 单股票量化预测

数据截至 **{result.latest_date.date().isoformat()}**。预测目标为未来 {HORIZON} 个交易日累计收益是否超过 {THRESHOLD:.0%}，不是价格点位预测。

## 最新信号

- 概率：**{result.latest_probability:.1%}**
- 信号：**{result.latest_signal}**
- 收盘价：{latest['close']:.2f}
- 当前训练选择的因子：{', '.join(result.selected_features)}

## 走步验证（5 折）

| Accuracy | Balanced accuracy | Precision | ROC-AUC |
| ---: | ---: | ---: | ---: |
| {metrics['accuracy']:.3f} | {metrics['balanced_accuracy']:.3f} | {metrics['precision']:.3f} | {metrics['roc_auc']:.3f} |

每折均使用扩展训练窗口，并在训练与测试之间留出 {HORIZON} 个交易日间隔，防止未来 {HORIZON} 日标签重叠。因子选择只在各训练折中拟合。详情见 `walk_forward_folds.csv`。

## 可用性判断

{validation}

> 本报告是历史数据研究，不构成投资建议。单一股票、有限样本和因子筛选均可能导致样本外失效；请结合公告、停复牌、流动性和风险承受能力判断。
"""
    (output_dir / "README.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
