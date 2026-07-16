from __future__ import annotations

import time
from pathlib import Path
import pandas as pd
from tqdm import tqdm


class FullMarketIngestor:
    """Download one trading date at a time and persist immutable raw partitions."""

    def __init__(self, client, output_dir="data/raw/market_daily", sleep_seconds=0.25):
        self.client = client
        self.output_dir = Path(output_dir)
        self.sleep_seconds = sleep_seconds
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def trading_dates(self, start_date: str, end_date: str) -> list[str]:
        cal = self.client.pro.trade_cal(
            exchange="SSE",
            start_date=start_date.replace("-", ""),
            end_date=end_date.replace("-", ""),
            is_open="1",
            fields="cal_date,is_open",
        )
        return sorted(cal["cal_date"].astype(str).tolist())

    def _path(self, trade_date: str) -> Path:
        year = trade_date[:4]
        return self.output_dir / f"year={year}" / f"trade_date={trade_date}.parquet"

    def ingest(self, start_date: str, end_date: str, overwrite=False):
        dates = self.trading_dates(start_date, end_date)
        downloaded, cached, failed = 0, 0, []

        for trade_date in tqdm(dates, desc="Full-market daily ingestion"):
            path = self._path(trade_date)
            if path.exists() and not overwrite:
                cached += 1
                continue

            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                df = self.client.pro.daily(trade_date=trade_date)
                if df is None or df.empty:
                    failed.append((trade_date, "empty response"))
                    continue
                df["trade_date"] = pd.to_datetime(df["trade_date"])
                df.to_parquet(path, index=False)
                downloaded += 1
                time.sleep(self.sleep_seconds)
            except Exception as exc:
                failed.append((trade_date, str(exc)))
                time.sleep(self.sleep_seconds * 3)

        return {"downloaded": downloaded, "cached": cached, "failed": failed}
