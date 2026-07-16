from __future__ import annotations

import pandas as pd


def build_a_share_universe(
    stock_basic: pd.DataFrame,
    end_date: str,
    exclude_prefixes=("83", "87", "92"),
    min_list_days: int = 800,
    max_stocks: int | None = None,
) -> pd.DataFrame:
    """
    Build a clean MVP A-share universe.

    We exclude BSE-style prefixes by default and require enough listing history.
    This is intentionally conservative for a first data layer.
    """
    df = stock_basic.copy()
    end = pd.to_datetime(end_date)

    for prefix in exclude_prefixes:
        df = df[~df["ts_code"].astype(str).str.startswith(prefix)]

    df["list_days"] = (end - pd.to_datetime(df["list_date"])).dt.days
    df = df[df["list_days"] >= min_list_days]
    df = df.sort_values(["industry", "ts_code"]).reset_index(drop=True)

    if max_stocks is not None:
        df = df.head(max_stocks)

    return df
