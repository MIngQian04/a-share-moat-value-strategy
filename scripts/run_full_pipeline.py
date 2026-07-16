"""Run the reproducible strategy workflow.

Default mode uses the included minimal processed research sample and rebuilds
derived research/selection outputs locally.

Use --refresh-data to rebuild the data layer from configured market sources
before running the strategy workflow.
"""
import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_STEPS = [
    "scripts/run_cycle_exposure_candidates.py",
    "scripts/run_cycle_behavior.py",
    "scripts/run_cycle_opportunity_rank.py",
    "scripts/run_fundamental_direction.py",
    "scripts/run_quant_quality.py",
    "scripts/run_final_assembly.py",
    "scripts/run_complement_engine.py",
    "scripts/run_cycle_base_sequence_cppi.py",
    "scripts/run_current_cycle_decision.py",
    "scripts/generate_backtest_report.py",
]

REFRESH_STEPS = [
    "scripts/run_data_layer.py",
    "scripts/run_full_market_ingestion.py",
    "scripts/run_metadata_layer.py",
    "scripts/run_research_dataset.py",
]


def run(script: str) -> None:
    print(f"\n===== RUN {script} =====", flush=True)
    subprocess.run([sys.executable, script], cwd=PROJECT_ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the complete strategy workflow.")
    parser.add_argument(
        "--refresh-data",
        action="store_true",
        help="Refresh market data and rebuild the research dataset first.",
    )
    args = parser.parse_args()

    steps = (REFRESH_STEPS if args.refresh_data else []) + DEFAULT_STEPS
    for script in steps:
        run(script)

    print("\nFull strategy workflow finished.", flush=True)


if __name__ == "__main__":
    main()
