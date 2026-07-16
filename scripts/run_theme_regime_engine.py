# Allow running this file directly from the project root, e.g.
# python scripts/run_xxx.py
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pathlib import Path
import numpy as np
import pandas as pd


THEME_RETURNS_PATH = Path(
    "data/processed/research/theme_returns.parquet"
)

OUT_DAILY = Path(
    "data/processed/selection/theme_regime_history.csv"
)

OUT_LATEST = Path(
    "data/processed/selection/theme_regime_latest.csv"
)


TRADING_DAYS = 252

POSITION_LOOKBACK = 252
DRAWDOWN_LOOKBACK = 252


# ============================================================
# Evidence Scores
# ============================================================

def bottom_evidence(position, drawdown):
    score = 0

    if pd.notna(position):
        if position <= 0.30:
            score += 2
        elif position <= 0.50:
            score += 1

    if pd.notna(drawdown):
        if drawdown <= -0.30:
            score += 2
        elif drawdown <= -0.20:
            score += 1

    return score


def deceleration_evidence(r20, r60, r120):
    score = 0

    if any(pd.isna(x) for x in [r20, r60, r120]):
        return score

    if r20 > r60:
        score += 1

    if r60 > r120:
        score += 1

    if r20 > r120:
        score += 1

    return score


def momentum_recovery_evidence(r20, r60):
    score = 0

    if pd.isna(r20) or pd.isna(r60):
        return score

    if r20 > 0:
        score += 2
    elif r20 > -0.03:
        score += 1

    if r20 > r60:
        score += 1

    return score


# ============================================================
# State Machine
# ============================================================

def classify(row):
    position = row["theme_position_252"]
    dd = row["theme_drawdown_252"]

    r20 = row["ret_20"]
    r60 = row["ret_60"]
    r120 = row["ret_120"]

    bottom_score = row["bottom_evidence_score"]
    decel_score = row["deceleration_evidence_score"]
    momentum_score = row["momentum_recovery_score"]

    if pd.isna(position) or pd.isna(dd):
        return "UNKNOWN"

    # --------------------------------------------------------
    # Late Cycle
    # --------------------------------------------------------

    if (
        position >= 0.75
        and pd.notna(r20)
        and r20 < 0
    ):
        return "LATE_CYCLE"

    # --------------------------------------------------------
    # Expansion
    # --------------------------------------------------------

    if (
        position > 0.45
        and pd.notna(r20)
        and pd.notna(r60)
        and r20 > 0
        and r60 > 0
    ):
        return "EXPANSION"

    # --------------------------------------------------------
    # Bottom Recovery
    # Strong bottom evidence
    # Strong deceleration
    # Positive short-term momentum
    # --------------------------------------------------------

    if (
        bottom_score >= 3
        and decel_score >= 2
        and momentum_score >= 2
        and pd.notna(r20)
        and r20 > 0
    ):
        return "BOTTOM_RECOVERY"

    # --------------------------------------------------------
    # Stabilizing
    # Strong bottom evidence
    # Strong downside deceleration
    # --------------------------------------------------------

    if (
        bottom_score >= 3
        and decel_score >= 3
    ):
        return "STABILIZING"

    # --------------------------------------------------------
    # Early Stabilizing
    # Partial evidence of downside improvement
    # --------------------------------------------------------

    if (
        bottom_score >= 2
        and decel_score >= 2
        and momentum_score >= 1
    ):
        return "EARLY_STABILIZING"

    # --------------------------------------------------------
    # Deep Bottom Falling
    # Bottom location but still falling aggressively
    # --------------------------------------------------------

    if (
        bottom_score >= 3
        and pd.notna(r20)
        and pd.notna(r60)
        and r20 < -0.05
        and r60 < -0.08
        and r20 < r60
    ):
        return "DEEP_BOTTOM_FALLING"

    # --------------------------------------------------------
    # Contraction
    # --------------------------------------------------------

    if (
        pd.notna(r20)
        and pd.notna(r60)
        and r20 < 0
        and r60 < 0
    ):
        return "CONTRACTION"

    return "NEUTRAL"


# ============================================================
# Opportunity Score
# ============================================================

def opportunity_score(row):
    regime = row["theme_regime"]

    regime_base = {
        "BOTTOM_RECOVERY": 100,
        "STABILIZING": 70,
        "EARLY_STABILIZING": 55,
        "EXPANSION": 45,
        "NEUTRAL": 30,
        "DEEP_BOTTOM_FALLING": 15,
        "CONTRACTION": 10,
        "LATE_CYCLE": 5,
        "UNKNOWN": 0,
    }.get(regime, 0)

    evidence_bonus = (
        row["bottom_evidence_score"] * 2
        + row["deceleration_evidence_score"] * 3
        + row["momentum_recovery_score"] * 3
    )

    return float(
        regime_base + evidence_bonus
    )


# ============================================================
# Main
# ============================================================

def main():
    if not THEME_RETURNS_PATH.exists():
        raise FileNotFoundError(
            f"Missing {THEME_RETURNS_PATH}"
        )

    theme_ret = pd.read_parquet(
        THEME_RETURNS_PATH
    )

    if "trade_date" in theme_ret.columns:
        theme_ret["trade_date"] = pd.to_datetime(
            theme_ret["trade_date"]
        )

        theme_ret = theme_ret.set_index(
            "trade_date"
        )

    theme_ret = theme_ret.sort_index()

    rows = []

    for theme in theme_ret.columns:
        r = pd.to_numeric(
            theme_ret[theme],
            errors="coerce",
        ).dropna()

        nav = (
            1 + r
        ).cumprod()

        # ====================================================
        # Theme Position
        # ====================================================

        low_252 = (
            nav
            .rolling(
                POSITION_LOOKBACK,
                min_periods=120,
            )
            .min()
        )

        high_252 = (
            nav
            .rolling(
                POSITION_LOOKBACK,
                min_periods=120,
            )
            .max()
        )

        price_range = (
            high_252 - low_252
        )

        position_252 = (
            nav - low_252
        ) / price_range.replace(
            0,
            np.nan,
        )

        # ====================================================
        # Drawdown
        # ====================================================

        rolling_peak = (
            nav
            .rolling(
                DRAWDOWN_LOOKBACK,
                min_periods=120,
            )
            .max()
        )

        drawdown_252 = (
            nav / rolling_peak - 1
        )

        # ====================================================
        # Multi-Horizon Returns
        # ====================================================

        ret_20 = (
            nav / nav.shift(20) - 1
        )

        ret_60 = (
            nav / nav.shift(60) - 1
        )

        ret_120 = (
            nav / nav.shift(120) - 1
        )

        # ====================================================
        # Theme Frame
        # ====================================================

        df = pd.DataFrame({
            "trade_date": nav.index,
            "theme": theme,
            "theme_nav": nav.values,
            "theme_position_252":
                position_252.reindex(nav.index).values,
            "theme_drawdown_252":
                drawdown_252.reindex(nav.index).values,
            "ret_20":
                ret_20.reindex(nav.index).values,
            "ret_60":
                ret_60.reindex(nav.index).values,
            "ret_120":
                ret_120.reindex(nav.index).values,
        })

        # ====================================================
        # Evidence Layer
        # ====================================================

        df["bottom_evidence_score"] = df.apply(
            lambda row: bottom_evidence(
                row["theme_position_252"],
                row["theme_drawdown_252"],
            ),
            axis=1,
        )

        df["deceleration_evidence_score"] = df.apply(
            lambda row: deceleration_evidence(
                row["ret_20"],
                row["ret_60"],
                row["ret_120"],
            ),
            axis=1,
        )

        df["momentum_recovery_score"] = df.apply(
            lambda row: momentum_recovery_evidence(
                row["ret_20"],
                row["ret_60"],
            ),
            axis=1,
        )

        # ====================================================
        # State Machine
        # ====================================================

        df["theme_regime"] = df.apply(
            classify,
            axis=1,
        )

        df["theme_opportunity_score"] = df.apply(
            opportunity_score,
            axis=1,
        )

        # ====================================================
        # Portfolio State Signals
        # ====================================================

        df["entry_eligible"] = (
            df["theme_regime"]
            .eq("BOTTOM_RECOVERY")
        )

        df["hold_eligible"] = (
            df["theme_regime"]
            .isin([
                "BOTTOM_RECOVERY",
                "EXPANSION",
                "STABILIZING",
                "EARLY_STABILIZING",
            ])
        )

        df["exit_signal"] = (
            df["theme_regime"]
            .isin([
                "LATE_CYCLE",
                "CONTRACTION",
                "DEEP_BOTTOM_FALLING",
            ])
        )

        df["watchlist"] = (
            df["theme_regime"]
            .isin([
                "EARLY_STABILIZING",
                "STABILIZING",
                "BOTTOM_RECOVERY",
            ])
        )

        rows.append(df)

    # ========================================================
    # Combine
    # ========================================================

    result = pd.concat(
        rows,
        ignore_index=True,
    )

    result = result.sort_values(
        [
            "trade_date",
            "theme",
        ]
    )

    # ========================================================
    # Latest
    # ========================================================

    latest_date = result[
        "trade_date"
    ].max()

    latest = (
        result[
            result["trade_date"]
            == latest_date
        ]
        .sort_values(
            "theme_opportunity_score",
            ascending=False,
        )
        .copy()
    )

    # ========================================================
    # Save
    # ========================================================

    OUT_DAILY.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    result.to_csv(
        OUT_DAILY,
        index=False,
        encoding="utf-8-sig",
    )

    latest.to_csv(
        OUT_LATEST,
        index=False,
        encoding="utf-8-sig",
    )

    # ========================================================
    # Display
    # ========================================================

    display_cols = [
        "trade_date",
        "theme",
        "theme_regime",
        "theme_opportunity_score",
        "bottom_evidence_score",
        "deceleration_evidence_score",
        "momentum_recovery_score",
        "theme_position_252",
        "theme_drawdown_252",
        "ret_20",
        "ret_60",
        "ret_120",
        "entry_eligible",
        "hold_eligible",
        "exit_signal",
        "watchlist",
    ]

    print(
        "\n===== THEME REGIME V3 LATEST ====="
    )

    print(
        latest[
            display_cols
        ]
        .round(4)
        .to_string(index=False)
    )

    print(
        "\n===== ENTRY ELIGIBLE ====="
    )

    entry = latest[
        latest["entry_eligible"]
    ]

    if entry.empty:
        print(
            "NO ENTRY ELIGIBLE THEME"
        )
    else:
        print(
            entry[
                display_cols
            ]
            .round(4)
            .to_string(index=False)
        )

    print(
        "\n===== WATCHLIST ====="
    )

    watch = latest[
        latest["watchlist"]
    ]

    if watch.empty:
        print(
            "NO WATCHLIST THEME"
        )
    else:
        print(
            watch[
                display_cols
            ]
            .round(4)
            .to_string(index=False)
        )

    print(
        "\n===== REGIME COUNTS ====="
    )

    print(
        result
        .groupby(
            [
                "theme",
                "theme_regime",
            ]
        )
        .size()
        .unstack(
            fill_value=0
        )
        .to_string()
    )

    print(
        "\nsaved:",
        OUT_DAILY,
    )

    print(
        "saved:",
        OUT_LATEST,
    )


if __name__ == "__main__":
    main()
