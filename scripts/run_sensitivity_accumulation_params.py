# Allow running this file directly from the project root, e.g.
# python scripts/run_xxx.py
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pathlib import Path
import subprocess
import pandas as pd

SCRIPT = Path("scripts/run_cycle_base_sequence_cppi.py")
BACKUP = Path("scripts/run_cycle_base_time_survived_accumulation_v1.py")
OUT = Path("data/processed/research/accumulation_param_sensitivity.csv")

lookahead_list = [15, 20, 25]
invalidation_list = [-0.03, -0.05, -0.07]

base_text = BACKUP.read_text()
rows = []

for lookahead in lookahead_list:
    for invalidation in invalidation_list:
        text = base_text

        text = text.replace(
            "LOOKAHEAD_DAYS = 20",
            f"LOOKAHEAD_DAYS = {lookahead}",
        )

        text = text.replace(
            "INVALIDATION_DROP = -0.05",
            f"INVALIDATION_DROP = {invalidation}",
        )

        SCRIPT.write_text(text)

        subprocess.run(
            ["python3", str(SCRIPT)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        summary = pd.read_csv(
            "data/processed/selection/cycle_base_sequence_cppi_summary.csv"
        )

        row = summary.iloc[0].to_dict()
        row["lookahead_days"] = lookahead
        row["invalidation_drop"] = invalidation
        rows.append(row)

result = pd.DataFrame(rows)

cols = [
    "lookahead_days",
    "invalidation_drop",
    "annual_return",
    "annual_vol",
    "sharpe",
    "sortino",
    "max_drawdown",
    "calmar",
    "final_nav",
    "num_sequence_confirms",
    "num_step_adds",
    "num_drop_expansion",
    "avg_cycle_weight",
    "max_cycle_weight",
]

result = result[cols].sort_values(
    ["sharpe", "calmar"],
    ascending=[False, False],
)

OUT.parent.mkdir(parents=True, exist_ok=True)
result.to_csv(OUT, index=False, encoding="utf-8-sig")

SCRIPT.write_text(base_text)

print("\n===== ACCUMULATION PARAM SENSITIVITY =====")
print(result.round(4).to_string(index=False))
print("\nsaved:", OUT)
print("restored:", SCRIPT)
