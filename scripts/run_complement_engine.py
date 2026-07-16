# Allow running this file directly from the project root, e.g.
# python scripts/run_xxx.py
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pathlib import Path
import sys
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from selection.complement_engine import ComplementConfig, ComplementaryAssetEngine

FINAL_CANDIDATES_PATH = Path("data/processed/selection/final_candidates.csv")
RETURNS_PATH = Path("data/processed/selection/stock_return_matrix.csv")
SECURITY_MASTER_PATH = Path("data/processed/metadata/security_master.csv")
VALUATION_PATHS = [
    Path("data/processed/selection/complement_valuation.csv"),
    Path("data/processed/selection/classified_candidates.csv"),
    Path("data/processed/selection/screened_candidates_full.csv"),
]
OUTPUT_PATH = Path("data/processed/selection/complement_pairs.csv")


def read_optional(path: Path) -> pd.DataFrame | None:
    if path.exists():
        return pd.read_csv(path)
    return None


def find_valuation() -> pd.DataFrame | None:
    frames = []
    for path in VALUATION_PATHS:
        if path.exists():
            df = pd.read_csv(path)
            if "ts_code" in df.columns:
                frames.append(df)
    if not frames:
        return None
    return pd.concat(frames, ignore_index=True).drop_duplicates("ts_code")


if __name__ == "__main__":
    if not FINAL_CANDIDATES_PATH.exists():
        raise FileNotFoundError(f"Missing {FINAL_CANDIDATES_PATH}; run scripts/run_final_assembly.py first.")
    if not RETURNS_PATH.exists():
        raise FileNotFoundError(f"Missing {RETURNS_PATH}; run scripts/run_data_layer.py first.")

    final_candidates = pd.read_csv(FINAL_CANDIDATES_PATH)
    returns = pd.read_csv(RETURNS_PATH)
    security_master = read_optional(SECURITY_MASTER_PATH)
    valuation = find_valuation()

    engine = ComplementaryAssetEngine(
        ComplementConfig(
            top_n_per_cycle_asset=10,
            min_obs=120,
            downside_quantile=0.20,
        )
    )
    result = engine.build(
        final_candidates=final_candidates,
        returns=returns,
        security_master=security_master,
        optional_valuation=valuation,
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")

    if result.empty:
        print("No complement pairs generated. Check return matrix coverage and final_candidates rank-1 assets.")
    else:
        display_cols = [
            "theme", "cycle_ts_code", "cycle_name", "pair_rank", "candidate_ts_code",
            "candidate_name", "candidate_industry", "candidate_type", "complement_score",
            "downside_corr", "stress_return", "drawdown_overlap", "candidate_ann_vol",
            "valuation_score", "valuation_status",
        ]
        display_cols = [c for c in display_cols if c in result.columns]
        for theme in result["theme"].dropna().unique():
            print(f"\n===== {str(theme).upper()} COMPLEMENT PAIRS =====")
            print(result[result["theme"] == theme][display_cols].to_string(index=False))
        print(f"\nsaved: {OUTPUT_PATH}")
