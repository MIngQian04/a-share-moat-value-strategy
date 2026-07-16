# Allow direct execution from project root.
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from risk.risk_exit import RiskExitEngine, apply_position_action


CANDIDATES_PATH = Path("data/processed/selection/final_candidates.csv")
CLOSE_PATH = Path("data/processed/research/close.parquet")
OUT_PATH = Path("data/processed/selection/risk_exit_status.csv")


def main():
    candidates = pd.read_csv(CANDIDATES_PATH)
    close = pd.read_parquet(CLOSE_PATH)
    close.index = pd.to_datetime(close.index)
    close = close.sort_index()

    engine = RiskExitEngine()
    risk = engine.evaluate_candidates(candidates, close)

    merged = candidates.merge(risk, on=["theme", "ts_code"], how="left")
    merged = apply_position_action(merged)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    risk.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")
    merged.to_csv(CANDIDATES_PATH, index=False, encoding="utf-8-sig")

    print("\n===== RISK EXIT ENGINE =====")
    print(risk["risk_exit_status"].value_counts(dropna=False).to_string())

    triggered = risk[risk["risk_exit_status"].isin(["EXIT", "REDUCE"])].copy()
    if not triggered.empty:
        triggered = triggered.sort_values(
            ["risk_exit_status", "drawdown_from_peak"],
            ascending=[True, True],
        )
        print("\n===== EXIT / REDUCE CANDIDATES =====")
        print(
            triggered[
                [
                    "theme",
                    "ts_code",
                    "risk_exit_status",
                    "drawdown_from_peak",
                    "ret_20d",
                    "risk_exit_reason",
                ]
            ].to_string(index=False)
        )

    print("\nsaved:", OUT_PATH)
    print("updated:", CANDIDATES_PATH)


if __name__ == "__main__":
    main()
