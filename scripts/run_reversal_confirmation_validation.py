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


PROXY_RETURNS_PATH = Path(
    "data/processed/research/theme_proxy_returns.parquet"
)

NAV_PATH = Path(
    "data/processed/selection/single_theme_profile_nav.csv"
)

OUT_HISTORY = Path(
    "data/processed/selection/reversal_confirmation_history.csv"
)

OUT_EVENTS = Path(
    "data/processed/selection/reversal_confirmation_events.csv"
)

OUT_SUMMARY = Path(
    "data/processed/selection/reversal_confirmation_validation.csv"
)


FORWARD_WINDOWS = [20, 60, 120, 252]

LOW_POSITION_THRESHOLD = 0.35
VOLUME_PROXY_THRESHOLD = 1.50
MIN_CONFIRM_SCORE = 3


def forward_return(nav, horizon):
    return nav.shift(-horizon) / nav - 1.0


def main():

    proxy_ret = pd.read_parquet(
        PROXY_RETURNS_PATH
    )

    proxy_ret.index = pd.to_datetime(
        proxy_ret.index
    )

    nav_df = pd.read_csv(
        NAV_PATH
    )

    nav_df["trade_date"] = pd.to_datetime(
        nav_df["trade_date"]
    )

    nav_df = (
        nav_df
        .set_index("trade_date")
        .sort_index()
    )

    rows = []
    event_rows = []

    for theme in proxy_ret.columns:

        ret = pd.to_numeric(
            proxy_ret[theme],
            errors="coerce",
        )

        theme_nav = (
            1.0 + ret.fillna(0.0)
        ).cumprod()

        # --------------------------------------------------
        # PRICE / LOCATION STRUCTURE
        # --------------------------------------------------

        rolling_high_252 = (
            theme_nav
            .rolling(252, min_periods=120)
            .max()
        )

        rolling_low_252 = (
            theme_nav
            .rolling(252, min_periods=120)
            .min()
        )

        position_252 = (
            (
                theme_nav - rolling_low_252
            )
            /
            (
                rolling_high_252
                - rolling_low_252
            )
        )

        ret_20 = (
            theme_nav
            / theme_nav.shift(20)
            - 1.0
        )

        # --------------------------------------------------
        # EVIDENCE 1:
        # Bottom volume expansion proxy
        #
        # We currently only have return matrix, not true volume.
        # Therefore use absolute-return expansion as a temporary
        # activity proxy.
        # --------------------------------------------------

        abs_ret = ret.abs()

        activity_5 = (
            abs_ret
            .rolling(5)
            .mean()
        )

        activity_60 = (
            abs_ret
            .rolling(60)
            .mean()
        )

        activity_ratio = (
            activity_5
            / activity_60
        )

        bottom_activity_expansion = (
            (position_252 <= LOW_POSITION_THRESHOLD)
            &
            (
                activity_ratio
                >= VOLUME_PROXY_THRESHOLD
            )
        )

        # --------------------------------------------------
        # EVIDENCE 2:
        # Three consecutive positive days
        # --------------------------------------------------

        positive_day = ret > 0

        three_positive_days = (
            positive_day
            &
            positive_day.shift(1)
            &
            positive_day.shift(2)
        )

        low_three_positive = (
            (position_252 <= LOW_POSITION_THRESHOLD)
            &
            three_positive_days
        )

        # --------------------------------------------------
        # EVIDENCE 3:
        # 20D momentum recovery
        # --------------------------------------------------

        momentum_recovery = (
            (ret_20 > 0)
            &
            (
                ret_20.shift(5) <= 0
            )
        )

        # --------------------------------------------------
        # EVIDENCE 4:
        # Break short-term structure
        # --------------------------------------------------

        previous_20_high = (
            theme_nav
            .shift(1)
            .rolling(20)
            .max()
        )

        short_structure_break = (
            theme_nav
            > previous_20_high
        )

        # --------------------------------------------------
        # SCORE
        # --------------------------------------------------

        score = (
            bottom_activity_expansion.astype(int)
            + low_three_positive.astype(int)
            + momentum_recovery.astype(int)
            + short_structure_break.astype(int)
        )

        confirmed = (
            score >= MIN_CONFIRM_SCORE
        )

        # --------------------------------------------------
        # Only validate while this theme is actually held
        # --------------------------------------------------

        held = (
            nav_df["current_theme"]
            .astype(str)
            .eq(theme)
        )

        held = held.reindex(
            theme_nav.index
        ).fillna(False)

        confirmed_held = (
            confirmed
            &
            held
        )

        # --------------------------------------------------
        # First confirmation per holding episode only
        # --------------------------------------------------

        episode_start = (
            held
            &
            ~held.shift(1).fillna(False)
        )

        episode_id = (
            episode_start.astype(int)
            .cumsum()
        )

        first_confirm = pd.Series(
            False,
            index=theme_nav.index,
        )

        held_confirm_df = pd.DataFrame({
            "held": held,
            "confirmed": confirmed_held,
            "episode_id": episode_id,
        })

        for ep, g in held_confirm_df[
            held_confirm_df["held"]
        ].groupby("episode_id"):

            hits = g[
                g["confirmed"]
            ]

            if not hits.empty:
                first_confirm.loc[
                    hits.index[0]
                ] = True

        # --------------------------------------------------
        # Forward returns
        # --------------------------------------------------

        forward = {}

        for horizon in FORWARD_WINDOWS:
            forward[horizon] = forward_return(
                theme_nav,
                horizon,
            )

        for dt in theme_nav.index:

            row = {
                "trade_date": dt,
                "theme": theme,
                "held": bool(
                    held.loc[dt]
                ),
                "position_252":
                    position_252.loc[dt],
                "ret_20":
                    ret_20.loc[dt],
                "activity_ratio":
                    activity_ratio.loc[dt],
                "bottom_activity_expansion":
                    bool(
                        bottom_activity_expansion.loc[dt]
                    ),
                "low_three_positive":
                    bool(
                        low_three_positive.loc[dt]
                    ),
                "momentum_recovery":
                    bool(
                        momentum_recovery.loc[dt]
                    ),
                "short_structure_break":
                    bool(
                        short_structure_break.loc[dt]
                    ),
                "reversal_score":
                    int(score.loc[dt])
                    if pd.notna(score.loc[dt])
                    else 0,
                "reversal_confirmed":
                    bool(confirmed.loc[dt]),
                "first_confirm_in_episode":
                    bool(first_confirm.loc[dt]),
            }

            for horizon in FORWARD_WINDOWS:
                row[
                    f"forward_{horizon}d"
                ] = forward[horizon].loc[dt]

            rows.append(row)

            if first_confirm.loc[dt]:

                event_row = row.copy()

                event_rows.append(
                    event_row
                )

    history = pd.DataFrame(rows)

    events = pd.DataFrame(
        event_rows
    )

    # ======================================================
    # VALIDATION SUMMARY
    # ======================================================

    summary_rows = []

    for horizon in FORWARD_WINDOWS:

        col = f"forward_{horizon}d"

        # confirmed events

        confirmed_returns = (
            events[col]
            .dropna()
            if not events.empty
            else pd.Series(dtype=float)
        )

        # all held days baseline

        baseline_returns = (
            history.loc[
                history["held"],
                col,
            ]
            .dropna()
        )

        for group_name, s in [
            (
                "REVERSAL_CONFIRMED",
                confirmed_returns,
            ),
            (
                "ALL_HELD_DAYS",
                baseline_returns,
            ),
        ]:

            summary_rows.append({
                "group": group_name,
                "horizon": horizon,
                "n": len(s),
                "mean_return":
                    s.mean()
                    if len(s)
                    else np.nan,
                "median_return":
                    s.median()
                    if len(s)
                    else np.nan,
                "win_rate":
                    (s > 0).mean()
                    if len(s)
                    else np.nan,
                "p10":
                    s.quantile(0.10)
                    if len(s)
                    else np.nan,
                "p25":
                    s.quantile(0.25)
                    if len(s)
                    else np.nan,
            })

    summary = pd.DataFrame(
        summary_rows
    )

    OUT_HISTORY.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    history.to_csv(
        OUT_HISTORY,
        index=False,
        encoding="utf-8-sig",
    )

    events.to_csv(
        OUT_EVENTS,
        index=False,
        encoding="utf-8-sig",
    )

    summary.to_csv(
        OUT_SUMMARY,
        index=False,
        encoding="utf-8-sig",
    )

    print(
        "\n===== REVERSAL CONFIRMATION EVENTS ====="
    )

    if events.empty:
        print("NO EVENTS")
    else:
        cols = [
            "trade_date",
            "theme",
            "position_252",
            "ret_20",
            "activity_ratio",
            "bottom_activity_expansion",
            "low_three_positive",
            "momentum_recovery",
            "short_structure_break",
            "reversal_score",
            "forward_20d",
            "forward_60d",
            "forward_120d",
            "forward_252d",
        ]

        print(
            events[cols]
            .round(4)
            .to_string(index=False)
        )

    print(
        "\n===== VALIDATION SUMMARY ====="
    )

    print(
        summary
        .round(4)
        .to_string(index=False)
    )

    print(
        "\n===== EVENT COUNTS BY THEME ====="
    )

    if events.empty:
        print("NO EVENTS")
    else:
        print(
            events["theme"]
            .value_counts()
            .to_string()
        )

    print(
        "\nsaved:",
        OUT_HISTORY,
    )

    print(
        "saved:",
        OUT_EVENTS,
    )

    print(
        "saved:",
        OUT_SUMMARY,
    )


if __name__ == "__main__":
    main()
