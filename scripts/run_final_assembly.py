# Allow running this file directly from the project root, e.g.
# python scripts/run_xxx.py
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pathlib import Path
import pandas as pd

from selection.final_assembly import FinalCandidateAssembler


REACTION_PATH = Path("data/processed/research/cycle_opportunity_rank.csv")

QUALITY_CANDIDATES = [
    Path("data/processed/selection/quant_quality_v3.csv"),
    Path("data/processed/selection/quant_quality_v2.csv"),
    Path("data/processed/selection/quant_quality_v1.csv"),
]

OUTPUT_PATH = Path("data/processed/selection/final_candidates.csv")


def find_quality_file() -> Path:
    for path in QUALITY_CANDIDATES:
        if path.exists():
            df = pd.read_csv(path, nrows=2)
            if "quant_quality_score" in df.columns:
                return path
    raise FileNotFoundError(
        "No usable quant quality file found. Expected quant_quality_v3/v2 with "
        "quant_quality_score."
    )


if __name__ == "__main__":
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    if not REACTION_PATH.exists():
        raise FileNotFoundError(
            f"Missing reaction file: {REACTION_PATH}. "
            "Run scripts/run_cycle_opportunity_rank.py first."
        )

    quality_path = find_quality_file()

    print(f"reaction input: {REACTION_PATH}")
    print(f"quality input : {quality_path}")

    reaction = pd.read_csv(REACTION_PATH)
    quality = pd.read_csv(quality_path)

    required_reaction_cols = [
        "theme",
        "ts_code",
        "upside_elasticity",
        "downside_elasticity",
        "cycle_convexity",
        "elasticity_class",
        "cycle_behavior_profile",
        "theme_rank",
    ]

    missing = [c for c in required_reaction_cols if c not in reaction.columns]
    if missing:
        raise ValueError(f"Reaction file missing required columns: {missing}")

    assembler = FinalCandidateAssembler(top_n_per_theme=10)
    result = assembler.assemble(reaction=reaction, quality=quality)

    result.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")

    print("\nreaction score source counts:")
    print(result["reaction_score_source"].value_counts(dropna=False).to_string())

    display_cols = [
        "assembly_rank",
        "ts_code",
        "theme_similarity",
        "upside_elasticity",
        "downside_elasticity",
        "cycle_convexity",
        "elasticity_class",
        "cycle_behavior_profile",
        "cycle_reaction_score_final",
        "reaction_score_source",
        "cycle_reaction_rank_final",
        "fundamental_direction",
        "survival_status",
        "capacity_status",
        "quant_quality_score",
        "quant_quality_rank",
        "quality_evidence",
        "final_bucket",
    ]
    display_cols = [c for c in display_cols if c in result.columns]

    for theme in result["theme"].dropna().unique():
        print(f"\n===== {theme.upper()} FINAL ASSEMBLY V1.2 =====")
        theme_df = result[result["theme"] == theme]
        print(theme_df[display_cols].to_string(index=False))

    print(f"\nsaved: {OUTPUT_PATH}")
