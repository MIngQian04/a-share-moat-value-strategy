# Allow running this file directly from the project root, e.g.
# python scripts/run_pipeline.py --stage final
import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

PIPELINES = {
    "final": [
        "scripts/run_final_assembly.py",
        "scripts/run_complement_engine.py",
        "scripts/run_current_cycle_decision.py",
    ],
    "data": [
        "scripts/run_data_layer.py",
        "scripts/run_full_market_ingestion.py",
        "scripts/run_metadata_layer.py",
        "scripts/run_research_dataset.py",
    ],
    "research": [
        "scripts/run_cycle_exposure_candidates.py",
        "scripts/run_cycle_behavior.py",
        "scripts/run_cycle_opportunity_rank.py",
        "scripts/run_quant_quality.py",
        "scripts/run_fundamental_direction.py",
        "scripts/run_final_assembly.py",
    ],
}


def run_script(script: str) -> None:
    print(f"\n===== RUN {script} =====")
    subprocess.run([sys.executable, script], cwd=PROJECT_ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run project pipeline stages.")
    parser.add_argument(
        "--stage",
        choices=sorted(PIPELINES),
        default="final",
        help="Pipeline stage to run. Default: final.",
    )
    args = parser.parse_args()

    for script in PIPELINES[args.stage]:
        run_script(script)

    print("\nPipeline finished.")


if __name__ == "__main__":
    main()
