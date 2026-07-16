# Allow running this file directly from the project root, e.g.
# python scripts/run_xxx.py
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pathlib import Path
import pandas as pd

IN_PATH = Path("data/processed/selection/complement_pairs.csv")
OUT_PATH = Path("data/processed/selection/qualified_complement_pairs.csv")

# ============================================================
# Partner Qualification Thresholds
# ============================================================

# Pair relationship gates
MAX_DOWNSIDE_CORR = 0.30
MIN_STRESS_RETURN = -0.015
MAX_DRAWDOWN_OVERLAP = 0.50

# Standalone partner risk gates
MAX_CANDIDATE_ANN_VOL = 0.35
MIN_CANDIDATE_ANN_RETURN = 0.00
MIN_CANDIDATE_MAX_DRAWDOWN = -0.60

# Valuation gate
MIN_VALUATION_SCORE = 50.0


def fail_if_missing(row, col, reason, reasons):
    if col not in row.index or pd.isna(row[col]):
        reasons.append(reason)
        return True
    return False


def qualify(row):
    reasons = []

    # --------------------------------------------------------
    # Pair relationship qualification
    # --------------------------------------------------------

    if not fail_if_missing(
        row,
        "downside_corr",
        "MISSING_DOWNSIDE_CORR",
        reasons,
    ):
        if row["downside_corr"] > MAX_DOWNSIDE_CORR:
            reasons.append("HIGH_DOWNSIDE_CORR")

    if not fail_if_missing(
        row,
        "stress_return",
        "MISSING_STRESS_RETURN",
        reasons,
    ):
        if row["stress_return"] < MIN_STRESS_RETURN:
            reasons.append("POOR_STRESS_RETURN")

    if not fail_if_missing(
        row,
        "drawdown_overlap",
        "MISSING_DRAWDOWN_OVERLAP",
        reasons,
    ):
        if row["drawdown_overlap"] > MAX_DRAWDOWN_OVERLAP:
            reasons.append("HIGH_DRAWDOWN_OVERLAP")

    # --------------------------------------------------------
    # Standalone partner survival qualification
    # --------------------------------------------------------

    if not fail_if_missing(
        row,
        "candidate_ann_vol",
        "MISSING_CANDIDATE_VOL",
        reasons,
    ):
        if row["candidate_ann_vol"] > MAX_CANDIDATE_ANN_VOL:
            reasons.append("HIGH_CANDIDATE_VOL")

    if not fail_if_missing(
        row,
        "candidate_ann_return",
        "MISSING_CANDIDATE_RETURN",
        reasons,
    ):
        if row["candidate_ann_return"] <= MIN_CANDIDATE_ANN_RETURN:
            reasons.append("NEGATIVE_LONG_TERM_RETURN")

    if not fail_if_missing(
        row,
        "candidate_max_drawdown",
        "MISSING_CANDIDATE_MAX_DRAWDOWN",
        reasons,
    ):
        if row["candidate_max_drawdown"] < MIN_CANDIDATE_MAX_DRAWDOWN:
            reasons.append("EXCESSIVE_MAX_DRAWDOWN")

    # --------------------------------------------------------
    # Valuation qualification
    # --------------------------------------------------------

    if not fail_if_missing(
        row,
        "valuation_score",
        "MISSING_VALUATION_SCORE",
        reasons,
    ):
        if row["valuation_score"] < MIN_VALUATION_SCORE:
            reasons.append("LOW_VALUATION_SCORE")

    return reasons


def main():
    if not IN_PATH.exists():
        raise FileNotFoundError(
            f"Missing {IN_PATH}. Run complement engine first."
        )

    df = pd.read_csv(IN_PATH)

    df["qualification_reasons"] = df.apply(
        lambda row: "|".join(qualify(row)),
        axis=1,
    )

    df["partner_qualified"] = df["qualification_reasons"].eq("")

    qualified = df[df["partner_qualified"]].copy()

    df["qualified_pair_rank"] = pd.NA

    if not qualified.empty:
        qualified = qualified.sort_values(
            ["theme", "complement_score"],
            ascending=[True, False],
        ).copy()

        qualified["qualified_pair_rank"] = (
            qualified.groupby("theme").cumcount() + 1
        )

        rank_map = qualified.set_index(
            ["theme", "cycle_ts_code", "candidate_ts_code"]
        )["qualified_pair_rank"]

        idx = df.set_index(
            ["theme", "cycle_ts_code", "candidate_ts_code"]
        ).index

        df["qualified_pair_rank"] = idx.map(rank_map)

    df.to_csv(
        OUT_PATH,
        index=False,
        encoding="utf-8-sig",
    )

    print("\n===== PARTNER QUALIFICATION SUMMARY =====")

    summary = (
        df.groupby("theme")["partner_qualified"]
        .agg(["sum", "count"])
        .rename(
            columns={
                "sum": "qualified",
                "count": "total_candidates",
            }
        )
    )

    summary["qualification_rate"] = (
        summary["qualified"]
        / summary["total_candidates"]
    )

    print(summary.to_string())

    print("\n===== REJECTION REASONS =====")

    rejected = df[~df["partner_qualified"]]

    if rejected.empty:
        print("No rejected partners.")
    else:
        reason_counts = (
            rejected["qualification_reasons"]
            .str.split("|")
            .explode()
            .value_counts()
        )

        print(reason_counts.to_string())

    print("\n===== QUALIFIED RANK 1 =====")

    rank1 = df[df["qualified_pair_rank"] == 1].copy()

    if rank1.empty:
        print("None")
    else:
        cols = [
            "theme",
            "cycle_ts_code",
            "candidate_ts_code",
            "candidate_name",
            "candidate_industry",
            "complement_score",
            "valuation_score",
            "downside_corr",
            "stress_return",
            "drawdown_overlap",
            "candidate_ann_vol",
            "candidate_ann_return",
            "candidate_max_drawdown",
            "qualified_pair_rank",
        ]

        cols = [c for c in cols if c in rank1.columns]

        print(
            rank1[cols]
            .round(4)
            .to_string(index=False)
        )

    print("\nsaved:", OUT_PATH)


if __name__ == "__main__":
    main()
