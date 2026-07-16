from __future__ import annotations

import pandas as pd

def clean_date(date: str) -> str:
    """Convert YYYY-MM-DD or YYYYMMDD into YYYYMMDD for Tushare."""
    return str(date).replace("-", "")

def to_datetime_index(df: pd.DataFrame, date_col: str = "trade_date") -> pd.DataFrame:
    out = df.copy()
    # CSV caches infer Tushare's YYYYMMDD values as integers.  Pandas otherwise
    # treats those integers as nanoseconds from 1970, silently corrupting dates.
    values = out[date_col].astype(str).str.replace(r"\.0$", "", regex=True)
    out[date_col] = pd.to_datetime(values, format="%Y%m%d", errors="coerce")
    if out[date_col].isna().any():
        raise ValueError(f"Could not parse all values in {date_col} as YYYYMMDD")
    return out.sort_values(date_col).set_index(date_col)
