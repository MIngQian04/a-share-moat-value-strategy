# Risk Exit Engine v1

This patch adds a daily price-risk overlay independent from the existing cycle/fundamental state machine.

## Core idea

Fundamental state explains why a stock may be held. Risk Exit decides whether price damage requires reducing or exiting.

Risk Exit has higher priority than `HARVESTING`, `RECOVERING`, or other cycle labels.

## Default rules

- `EXIT` if 120-trading-day peak drawdown <= -25%.
- `EXIT` if price is below MA60 and 20-day return <= -10%.
- `REDUCE` if 120-trading-day peak drawdown <= -15%.
- `REDUCE` if price is below MA60 and 20-day return is negative.
- Otherwise `HOLD`.

## Generated columns

- `risk_exit_status`
- `risk_exit_reason`
- `current_price`
- `peak_price`
- `drawdown_from_peak`
- `ma60`
- `ret_20d`
- `position_action`

## Run

```bash
python scripts/run_risk_exit_engine.py
```

Or insert it into `scripts/run_pipeline.py` after final assembly and before current decision report.
