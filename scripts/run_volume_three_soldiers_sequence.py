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

OPEN = Path("data/processed/research/rank1_open.parquet")
HIGH = Path("data/processed/research/rank1_high.parquet")
LOW = Path("data/processed/research/rank1_low.parquet")
CLOSE = Path("data/processed/research/rank1_close.parquet")
AMOUNT = Path("data/processed/research/rank1_amount.parquet")

NAV_PATH = Path("data/processed/selection/single_theme_profile_nav.csv")

OUT_EVENTS = Path("data/processed/selection/volume_three_soldiers_events.csv")
OUT_SUMMARY = Path("data/processed/selection/volume_three_soldiers_validation.csv")
OUT_HISTORY = Path("data/processed/selection/volume_three_soldiers_history.csv")

FORWARD_WINDOWS = [20, 60, 120, 252]

LOW_POSITION_THRESHOLD = 0.35
AMOUNT_RATIO_THRESHOLD = 1.50
VOLUME_LOOKAHEAD_DAYS = 20
INVALIDATION_DROP = -0.05
THREE_DAY_GAIN_THRESHOLD = 0.05


def forward_return(nav, horizon):
    return nav.shift(-horizon) / nav - 1.0


def build_three_soldiers(open_, close, high, low):
    bullish = close > open_

    higher_close = (
        (close > close.shift(1))
        & (close.shift(1) > close.shift(2))
    )

    three_bullish = (
        bullish
        & bullish.shift(1)
        & bullish.shift(2)
    )

    three_day_gain = close / close.shift(3) - 1.0

    body = (close - open_).abs()
    range_ = (high - low).replace(0, np.nan)

    body_ratio = body / range_

    solid_body = (
        (body_ratio >= 0.35)
        & (body_ratio.shift(1) >= 0.35)
        & (body_ratio.shift(2) >= 0.35)
    )

    return (
        three_bullish
        & higher_close
        & (three_day_gain >= THREE_DAY_GAIN_THRESHOLD)
        & solid_body
    )


def main():
    open_df = pd.read_parquet(OPEN)
    high_df = pd.read_parquet(HIGH)
    low_df = pd.read_parquet(LOW)
    close_df = pd.read_parquet(CLOSE)
    amount_df = pd.read_parquet(AMOUNT)

    nav_df = pd.read_csv(NAV_PATH)
    nav_df["trade_date"] = pd.to_datetime(nav_df["trade_date"])
    nav_df = nav_df.set_index("trade_date").sort_index()

    history_rows = []
    event_rows = []

    for theme in close_df.columns:
        close = close_df[theme].dropna()
        idx = close.index

        open_ = open_df[theme].reindex(idx)
        high = high_df[theme].reindex(idx)
        low = low_df[theme].reindex(idx)
        amount = amount_df[theme].reindex(idx)

        nav = close / close.iloc[0]

        low_252 = nav.rolling(252, min_periods=120).min()
        high_252 = nav.rolling(252, min_periods=120).max()
        position_252 = (nav - low_252) / (high_252 - low_252)

        amount_ratio = amount.rolling(5).mean() / amount.rolling(60).mean()

        bottom_volume_event = (
            (position_252 <= LOW_POSITION_THRESHOLD)
            & (amount_ratio >= AMOUNT_RATIO_THRESHOLD)
        )

        three_soldiers = build_three_soldiers(open_, close, high, low)

        held = (
            nav_df["current_theme"]
            .astype(str)
            .eq(theme)
            .reindex(idx)
            .fillna(False)
        )

        state = "BASE_POSITION"
        volume_event_date = None
        volume_event_low = np.nan
        days_since_volume = 0

        episode_start = held & ~held.shift(1).fillna(False)
        episode_id = episode_start.astype(int).cumsum()

        already_confirmed_episode = set()

        forwards = {w: forward_return(nav, w) for w in FORWARD_WINDOWS}

        for dt in idx:
            is_held = bool(held.loc[dt])
            ep = int(episode_id.loc[dt]) if is_held else -1

            confirmed_today = False
            action = ""

            if not is_held:
                state = "BASE_POSITION"
                volume_event_date = None
                volume_event_low = np.nan
                days_since_volume = 0

            else:
                if state == "BASE_POSITION":
                    if bool(bottom_volume_event.loc[dt]) and ep not in already_confirmed_episode:
                        state = "VOLUME_EVENT_DETECTED"
                        volume_event_date = dt
                        volume_event_low = float(low.loc[dt])
                        days_since_volume = 0
                        action = "BOTTOM_VOLUME_EVENT"

                elif state == "VOLUME_EVENT_DETECTED":
                    days_since_volume += 1

                    current_low = float(low.loc[dt])
                    invalidation_price = volume_event_low * (1 + INVALIDATION_DROP)

                    if current_low < invalidation_price:
                        state = "BASE_POSITION"
                        volume_event_date = None
                        volume_event_low = np.nan
                        days_since_volume = 0
                        action = "VOLUME_EVENT_INVALIDATED"

                    elif days_since_volume > VOLUME_LOOKAHEAD_DAYS:
                        state = "BASE_POSITION"
                        volume_event_date = None
                        volume_event_low = np.nan
                        days_since_volume = 0
                        action = "VOLUME_EVENT_EXPIRED"

                    elif bool(three_soldiers.loc[dt]):
                        confirmed_today = True
                        already_confirmed_episode.add(ep)
                        action = "SEQUENCE_CONFIRMED"

                        event = {
                            "trade_date": dt,
                            "theme": theme,
                            "volume_event_date": volume_event_date,
                            "days_after_volume": days_since_volume,
                            "position_252": position_252.loc[dt],
                            "amount_ratio": amount_ratio.loc[dt],
                            "close": close.loc[dt],
                            "volume_event_low": volume_event_low,
                        }

                        for w in FORWARD_WINDOWS:
                            event[f"forward_{w}d"] = forwards[w].loc[dt]

                        event_rows.append(event)

                        state = "CONFIRMED"

                elif state == "CONFIRMED":
                    pass

            row = {
                "trade_date": dt,
                "theme": theme,
                "held": is_held,
                "state": state,
                "action": action,
                "bottom_volume_event": bool(bottom_volume_event.loc[dt]),
                "three_soldiers": bool(three_soldiers.loc[dt]),
                "sequence_confirmed": confirmed_today,
                "position_252": position_252.loc[dt],
                "amount_ratio": amount_ratio.loc[dt],
            }

            for w in FORWARD_WINDOWS:
                row[f"forward_{w}d"] = forwards[w].loc[dt]

            history_rows.append(row)

    history = pd.DataFrame(history_rows)
    events = pd.DataFrame(event_rows)

    summary_rows = []

    for w in FORWARD_WINDOWS:
        col = f"forward_{w}d"

        confirmed = events[col].dropna() if not events.empty else pd.Series(dtype=float)
        held_days = history.loc[history["held"], col].dropna()

        for name, s in [
            ("VOLUME_THREE_SOLDIERS_CONFIRMED", confirmed),
            ("ALL_HELD_DAYS", held_days),
        ]:
            summary_rows.append({
                "group": name,
                "horizon": w,
                "n": len(s),
                "mean_return": s.mean() if len(s) else np.nan,
                "median_return": s.median() if len(s) else np.nan,
                "win_rate": (s > 0).mean() if len(s) else np.nan,
                "p10": s.quantile(0.10) if len(s) else np.nan,
                "p25": s.quantile(0.25) if len(s) else np.nan,
            })

    summary = pd.DataFrame(summary_rows)

    OUT_EVENTS.parent.mkdir(parents=True, exist_ok=True)
    events.to_csv(OUT_EVENTS, index=False, encoding="utf-8-sig")
    summary.to_csv(OUT_SUMMARY, index=False, encoding="utf-8-sig")
    history.to_csv(OUT_HISTORY, index=False, encoding="utf-8-sig")

    print("\n===== VOLUME → THREE SOLDIERS EVENTS =====")
    if events.empty:
        print("NO EVENTS")
    else:
        print(events.round(4).to_string(index=False))

    print("\n===== VALIDATION SUMMARY =====")
    print(summary.round(4).to_string(index=False))

    print("\n===== EVENT COUNTS BY THEME =====")
    if events.empty:
        print("NO EVENTS")
    else:
        print(events["theme"].value_counts().to_string())

    print("\nsaved:", OUT_EVENTS)
    print("saved:", OUT_SUMMARY)
    print("saved:", OUT_HISTORY)


if __name__ == "__main__":
    main()
