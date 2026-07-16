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

OUT_EVENTS = Path("data/processed/selection/reversal_v2_events.csv")
OUT_SUMMARY = Path("data/processed/selection/reversal_v2_validation.csv")

FORWARD_WINDOWS = [20, 60, 120, 252]
MIN_SCORE = 4

def fwd(nav, n):
    return nav.shift(-n) / nav - 1

def main():
    o = pd.read_parquet(OPEN)
    h = pd.read_parquet(HIGH)
    l = pd.read_parquet(LOW)
    c = pd.read_parquet(CLOSE)
    amt = pd.read_parquet(AMOUNT)

    nav_df = pd.read_csv(NAV_PATH)
    nav_df["trade_date"] = pd.to_datetime(nav_df["trade_date"])
    nav_df = nav_df.set_index("trade_date").sort_index()

    rows = []
    events = []

    for theme in c.columns:
        close = c[theme].dropna()
        idx = close.index

        open_ = o[theme].reindex(idx)
        high = h[theme].reindex(idx)
        low = l[theme].reindex(idx)
        amount = amt[theme].reindex(idx)

        nav = close / close.iloc[0]

        ret20 = nav / nav.shift(20) - 1
        ret60 = nav / nav.shift(60) - 1
        ret120 = nav / nav.shift(120) - 1

        low252 = nav.rolling(252, min_periods=120).min()
        high252 = nav.rolling(252, min_periods=120).max()
        pos252 = (nav - low252) / (high252 - low252)

        # Seller exhaustion
        no_new_low_20 = close > close.shift(1).rolling(20).min()
        drawdown_slowing = (ret20 > ret60) & (ret60 > ret120)
        medium_loss_narrowing = (ret60 > -0.15) | ((ret20 > ret60) & (ret20 > -0.05))
        bottom_dwell = (pos252 <= 0.45).rolling(20, min_periods=10).sum() >= 10

        seller_score = (
            no_new_low_20.astype(int)
            + drawdown_slowing.astype(int)
            + medium_loss_narrowing.astype(int)
            + bottom_dwell.astype(int)
        )

        seller_exhaustion = seller_score >= 3

        # Buyer confirmation
        amount_ratio = amount.rolling(5).mean() / amount.rolling(60).mean()
        real_amount_expansion = amount_ratio >= 1.5

        candle_body = (close - open_) / open_
        bullish_candle = close > open_
        three_bullish = bullish_candle & bullish_candle.shift(1) & bullish_candle.shift(2)

        higher_close_3 = (close > close.shift(1)) & (close.shift(1) > close.shift(2))
        red_three_soldiers = three_bullish & higher_close_3 & ((close / close.shift(3) - 1) >= 0.05)

        break_20_high = close > close.shift(1).rolling(20).max()
        momentum_turn_positive = (ret20 > 0) & (ret20.shift(5) <= 0)

        buyer_score = (
            real_amount_expansion.astype(int)
            + red_three_soldiers.astype(int)
            + break_20_high.astype(int)
            + momentum_turn_positive.astype(int)
        )

        buyer_confirmation = buyer_score >= 2

        reversal_score = seller_score + buyer_score
        reversal_v2 = seller_exhaustion & buyer_confirmation & (reversal_score >= MIN_SCORE)

        held = nav_df["current_theme"].astype(str).eq(theme).reindex(idx).fillna(False)

        episode_start = held & ~held.shift(1).fillna(False)
        episode_id = episode_start.astype(int).cumsum()

        first_confirm = pd.Series(False, index=idx)

        temp = pd.DataFrame({
            "held": held,
            "reversal_v2": reversal_v2,
            "episode_id": episode_id,
        })

        for ep, g in temp[temp["held"]].groupby("episode_id"):
            hits = g[g["reversal_v2"]]
            if not hits.empty:
                first_confirm.loc[hits.index[0]] = True

        forwards = {w: fwd(nav, w) for w in FORWARD_WINDOWS}

        for dt in idx:
            row = {
                "trade_date": dt,
                "theme": theme,
                "held": bool(held.loc[dt]),
                "position_252": pos252.loc[dt],
                "ret_20": ret20.loc[dt],
                "ret_60": ret60.loc[dt],
                "ret_120": ret120.loc[dt],
                "amount_ratio": amount_ratio.loc[dt],
                "seller_score": int(seller_score.loc[dt]) if pd.notna(seller_score.loc[dt]) else 0,
                "buyer_score": int(buyer_score.loc[dt]) if pd.notna(buyer_score.loc[dt]) else 0,
                "reversal_score": int(reversal_score.loc[dt]) if pd.notna(reversal_score.loc[dt]) else 0,
                "seller_exhaustion": bool(seller_exhaustion.loc[dt]),
                "buyer_confirmation": bool(buyer_confirmation.loc[dt]),
                "reversal_v2": bool(reversal_v2.loc[dt]),
                "first_confirm_in_episode": bool(first_confirm.loc[dt]),
                "real_amount_expansion": bool(real_amount_expansion.loc[dt]),
                "red_three_soldiers": bool(red_three_soldiers.loc[dt]),
                "break_20_high": bool(break_20_high.loc[dt]),
                "momentum_turn_positive": bool(momentum_turn_positive.loc[dt]),
            }

            for w in FORWARD_WINDOWS:
                row[f"forward_{w}d"] = forwards[w].loc[dt]

            rows.append(row)

            if first_confirm.loc[dt]:
                events.append(row.copy())

    hist = pd.DataFrame(rows)
    events = pd.DataFrame(events)

    summary_rows = []

    for w in FORWARD_WINDOWS:
        col = f"forward_{w}d"

        groups = {
            "REVERSAL_V2_FIRST_CONFIRM": events[col].dropna() if not events.empty else pd.Series(dtype=float),
            "ALL_HELD_DAYS": hist.loc[hist["held"], col].dropna(),
        }

        for name, s in groups.items():
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

    print("\n===== REVERSAL V2 EVENTS =====")
    if events.empty:
        print("NO EVENTS")
    else:
        cols = [
            "trade_date", "theme", "position_252", "ret_20", "ret_60", "ret_120",
            "amount_ratio", "seller_score", "buyer_score", "reversal_score",
            "forward_20d", "forward_60d", "forward_120d", "forward_252d"
        ]
        print(events[cols].round(4).to_string(index=False))

    print("\n===== REVERSAL V2 VALIDATION =====")
    print(summary.round(4).to_string(index=False))

    print("\n===== EVENT COUNTS BY THEME =====")
    if events.empty:
        print("NO EVENTS")
    else:
        print(events["theme"].value_counts().to_string())

    print("\nsaved:", OUT_EVENTS)
    print("saved:", OUT_SUMMARY)

if __name__ == "__main__":
    main()
