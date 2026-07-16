"""Generate today's transparent cycle/base/add and defensive portfolio sheet.

Uses cached full-market data. Run ``refresh_rotation_market_data.py`` first to
extend prices, volume and daily-basic through the latest completed trading day.
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from portfolio.rotation_signals import cycle_signal_table, defensive_signal_table, target_weights


def main() -> None:
    out_dir = Path("data/processed/portfolio")
    out_dir.mkdir(parents=True, exist_ok=True)
    candidates = pd.read_csv("data/processed/selection/final_candidates.csv")
    candidates = candidates[candidates["final_bucket"].eq("FINAL_CANDIDATE")].copy()
    close = pd.read_parquet("data/processed/research/close.parquet")
    volume = pd.read_parquet("data/processed/research/volume.parquet")
    cycle = cycle_signal_table(candidates, close, volume)
    cycle.to_csv(out_dir / "cycle_signals.csv", index=False, encoding="utf-8-sig")

    basic_path = out_dir / "daily_basic_latest.csv"
    if basic_path.exists():
        daily_basic = pd.read_csv(basic_path)
    else:
        daily_basic = pd.DataFrame(columns=["ts_code", "close", "dv_ratio", "pb", "total_mv"])

    approved = pd.read_csv("config/defensive_watchlist.csv", comment="#")
    defensive = defensive_signal_table(daily_basic, approved)
    defensive.to_csv(out_dir / "defensive_signals.csv", index=False, encoding="utf-8-sig")
    portfolio = target_weights(cycle, defensive)
    portfolio.to_csv(out_dir / "target_portfolio.csv", index=False, encoding="utf-8-sig")
    cash = portfolio.attrs["cash_weight"]
    summary = pd.DataFrame([{"as_of_date": pd.Timestamp(close.index.max()).date(), "cycle_weight": portfolio.attrs["cycle_weight"], "cash_weight": cash,
        "cycle_names": int((portfolio.get("allocation_bucket") == "cycle").sum()), "defensive_names": int((portfolio.get("allocation_bucket") == "defensive").sum()),
        "note": "Research output, not investment advice. Review liquidity, financial statements and corporate actions before trading."}])
    summary.to_csv(out_dir / "portfolio_summary.csv", index=False, encoding="utf-8-sig")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
