from __future__ import annotations

from pathlib import Path
import pandas as pd


class MarketStore:
    """Read locally partitioned market data without calling the API."""

    def __init__(self, root="data/raw/market_daily"):
        self.root = Path(root)

    def read(self, start_date=None, end_date=None, columns=None) -> pd.DataFrame:
        files = sorted(self.root.glob("year=*/trade_date=*.parquet"))
        frames = []
        for path in files:
            trade_date = path.stem.split("=")[-1]
            if start_date and trade_date < start_date.replace("-", ""):
                continue
            if end_date and trade_date > end_date.replace("-", ""):
                continue
            frames.append(pd.read_parquet(path, columns=columns))
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def matrix(self, value="close", start_date=None, end_date=None) -> pd.DataFrame:
        df = self.read(start_date, end_date, columns=["trade_date", "ts_code", value])
        if df.empty:
            return df
        return df.pivot(index="trade_date", columns="ts_code", values=value).sort_index()
