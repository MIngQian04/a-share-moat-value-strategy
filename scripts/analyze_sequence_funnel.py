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


TRADES_PATH = Path(
    "data/processed/selection/"
    "cycle_base_sequence_cppi_trades.csv"
)

CLOSE_PATH = Path(
    "data/processed/research/"
    "rank1_close.parquet"
)

OUT_PATH = Path(
    "data/processed/research/"
    "sequence_funnel_attribution.csv"
)

LOOKAHEAD_DAYS = 20


def get_loc(index, dt):
    try:
        loc = index.get_loc(dt)
    except KeyError:
        return None

    if not isinstance(loc, (int, np.integer)):
        return None

    return int(loc)


def forward_return(s, dt, horizon):
    loc = get_loc(s.index, dt)

    if loc is None:
        return np.nan

    end = loc + horizon

    if end >= len(s):
        return np.nan

    p0 = s.iloc[loc]
    p1 = s.iloc[end]

    if pd.isna(p0) or pd.isna(p1) or p0 <= 0:
        return np.nan

    return p1 / p0 - 1.0


def max_forward_gain(s, dt, horizon):
    loc = get_loc(s.index, dt)

    if loc is None:
        return np.nan

    p0 = s.iloc[loc]

    if pd.isna(p0) or p0 <= 0:
        return np.nan

    future = s.iloc[
        loc + 1:
        min(loc + horizon + 1, len(s))
    ].dropna()

    if future.empty:
        return np.nan

    return future.max() / p0 - 1.0


def max_forward_drawdown(s, dt, horizon):
    loc = get_loc(s.index, dt)

    if loc is None:
        return np.nan

    p0 = s.iloc[loc]

    if pd.isna(p0) or p0 <= 0:
        return np.nan

    future = s.iloc[
        loc + 1:
        min(loc + horizon + 1, len(s))
    ].dropna()

    if future.empty:
        return np.nan

    return future.min() / p0 - 1.0


def main():
    trades = pd.read_csv(TRADES_PATH)

    trades["trade_date"] = pd.to_datetime(
        trades["trade_date"]
    )

    trades = trades.sort_values(
        "trade_date"
    ).reset_index(drop=True)

    close = pd.read_parquet(CLOSE_PATH)
    close.index = pd.to_datetime(close.index)
    close = close.sort_index()

    resolution_actions = {
        "VOLUME_INVALIDATED",
        "VOLUME_EXPIRED",
        "SEQUENCE_CONFIRMED_OPEN_STEP_RISK",
        "ACCUMULATION_CONFIRMED_OPEN_STEP_RISK",
    }

    bottom_events = trades[
        trades["action"] == "BOTTOM_VOLUME"
    ].copy()

    rows = []

    for _, event in bottom_events.iterrows():
        start_dt = event["trade_date"]
        theme = event["theme"]

        if theme not in close.columns:
            continue

        s = close[theme].dropna()

        start_loc = get_loc(s.index, start_dt)

        if start_loc is None:
            continue

        max_loc = min(
            start_loc + LOOKAHEAD_DAYS + 1,
            len(s) - 1,
        )

        max_dt = s.index[max_loc]

        future_actions = trades[
            (trades["theme"] == theme)
            & (trades["trade_date"] > start_dt)
            & (trades["trade_date"] <= max_dt)
            & (
                trades["action"]
                .isin(resolution_actions)
            )
        ].sort_values("trade_date")

        if future_actions.empty:
            outcome = "NO_RESOLUTION_IN_WINDOW"
            resolution_dt = pd.NaT
            days_to_resolution = np.nan
        else:
            first = future_actions.iloc[0]

            outcome = first["action"]
            resolution_dt = first["trade_date"]

            resolution_loc = get_loc(
                s.index,
                resolution_dt,
            )

            if resolution_loc is None:
                days_to_resolution = np.nan
            else:
                days_to_resolution = (
                    resolution_loc - start_loc
                )

        row = {
            "volume_event_date": start_dt,
            "theme": theme,
            "amount_ratio": event.get(
                "amount_ratio",
                np.nan,
            ),
            "position_252": event.get(
                "position_252",
                np.nan,
            ),
            "outcome": outcome,
            "resolution_date": resolution_dt,
            "days_to_resolution":
                days_to_resolution,
        }

        for h in [20, 60, 120]:
            row[f"forward_{h}d"] = (
                forward_return(
                    s,
                    start_dt,
                    h,
                )
            )

            row[f"max_gain_{h}d"] = (
                max_forward_gain(
                    s,
                    start_dt,
                    h,
                )
            )

            row[f"max_drawdown_{h}d"] = (
                max_forward_drawdown(
                    s,
                    start_dt,
                    h,
                )
            )

        rows.append(row)

    result = pd.DataFrame(rows)

    result = result.sort_values(
        [
            "outcome",
            "max_gain_60d",
        ],
        ascending=[
            True,
            False,
        ],
    )

    OUT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    result.to_csv(
        OUT_PATH,
        index=False,
        encoding="utf-8-sig",
    )

    print("\n===== SEQUENCE FUNNEL =====")

    print(
        result["outcome"]
        .value_counts(dropna=False)
        .to_string()
    )

    perf_cols = [
        "forward_20d",
        "forward_60d",
        "forward_120d",
        "max_gain_20d",
        "max_gain_60d",
        "max_gain_120d",
        "max_drawdown_20d",
        "max_drawdown_60d",
        "max_drawdown_120d",
    ]

    print(
        "\n===== OUTCOME PERFORMANCE ====="
    )

    print(
        result.groupby("outcome")[
            perf_cols
        ]
        .mean()
        .round(4)
        .to_string()
    )

    print(
        "\n===== POSSIBLE FALSE NEGATIVES ====="
    )

    false_negative = result[
        (
            result["outcome"].isin([
                "VOLUME_EXPIRED",
                "NO_RESOLUTION_IN_WINDOW",
            ])
        )
        & (
            result["max_gain_60d"] >= 0.20
        )
    ].copy()

    cols = [
        "volume_event_date",
        "theme",
        "outcome",
        "amount_ratio",
        "position_252",
        "days_to_resolution",
        "forward_20d",
        "forward_60d",
        "max_gain_20d",
        "max_gain_60d",
        "max_drawdown_60d",
    ]

    if false_negative.empty:
        print("NO FALSE NEGATIVES")
    else:
        print(
            false_negative[cols]
            .sort_values(
                "max_gain_60d",
                ascending=False,
            )
            .to_string(index=False)
        )

    print(
        "\n===== INVALID DAYS CHECK ====="
    )

    bad = result[
        result["days_to_resolution"]
        > LOOKAHEAD_DAYS
    ]

    print(
        bad[
            [
                "volume_event_date",
                "theme",
                "outcome",
                "days_to_resolution",
            ]
        ].to_string(index=False)
        if not bad.empty
        else "PASS: NO RESOLUTION > LOOKAHEAD_DAYS"
    )

    print("\nsaved:", OUT_PATH)


if __name__ == "__main__":
    main()
