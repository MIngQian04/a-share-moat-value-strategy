from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional

import pandas as pd
from dotenv import load_dotenv

from utils.date_utils import clean_date, to_datetime_index


class TushareClient:
    """
    Thin Tushare wrapper with:
    - env-based token loading
    - local CSV cache
    - consistent datetime index
    - simple retry/sleep protection

    Never hard-code your token in source code.
    """

    def __init__(
        self,
        token: Optional[str] = None,
        data_dir: str | Path = "data/raw",
        sleep_seconds: float = 0.25,
        max_retries: int = 3,
        request_timeout_seconds: int = 30,
    ):
        load_dotenv()
        self.token = token or os.getenv("TUSHARE_TOKEN")
        if not self.token:
            raise ValueError("Missing TUSHARE_TOKEN. Put it in .env or export it in your shell.")

        import tushare as ts

        ts.set_token(self.token)
        self.pro = ts.pro_api(timeout=request_timeout_seconds)
        self.data_dir = Path(data_dir)
        self.sleep_seconds = sleep_seconds
        self.max_retries = max_retries
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _cached_call(self, cache_path: Path, func, overwrite: bool = False, **kwargs) -> pd.DataFrame:
        cache_path.parent.mkdir(parents=True, exist_ok=True)

        if cache_path.exists() and not overwrite:
            return pd.read_csv(cache_path)

        last_error = None
        for _ in range(self.max_retries):
            try:
                df = func(**kwargs)
                time.sleep(self.sleep_seconds)
                df.to_csv(cache_path, index=False, encoding="utf-8-sig")
                return df
            except Exception as exc:
                last_error = exc
                time.sleep(self.sleep_seconds * 3)

        raise RuntimeError(f"Tushare call failed after retries: {last_error}")

    def stock_basic(self, overwrite: bool = False) -> pd.DataFrame:
        path = self.data_dir / "basic" / "stock_basic.csv"
        df = self._cached_call(
            path,
            self.pro.stock_basic,
            overwrite=overwrite,
            exchange="",
            list_status="L",
            fields="ts_code,symbol,name,area,industry,list_date,market",
        )
        df["list_date"] = pd.to_datetime(df["list_date"], errors="coerce")
        return df

    def index_daily(self, ts_code: str, start_date: str, end_date: str, overwrite: bool = False) -> pd.DataFrame:
        path = self.data_dir / "index" / f"{ts_code}_{clean_date(start_date)}_{clean_date(end_date)}.csv"
        df = self._cached_call(
            path,
            self.pro.index_daily,
            overwrite=overwrite,
            ts_code=ts_code,
            start_date=clean_date(start_date),
            end_date=clean_date(end_date),
        )
        return to_datetime_index(df)

    def stock_daily(self, ts_code: str, start_date: str, end_date: str, overwrite: bool = False) -> pd.DataFrame:
        path = self.data_dir / "stock" / f"{ts_code}_{clean_date(start_date)}_{clean_date(end_date)}.csv"
        df = self._cached_call(
            path,
            self.pro.daily,
            overwrite=overwrite,
            ts_code=ts_code,
            start_date=clean_date(start_date),
            end_date=clean_date(end_date),
        )
        return to_datetime_index(df)

    def daily_basic(self, ts_code: str, start_date: str, end_date: str, overwrite: bool = False) -> pd.DataFrame:
        path = self.data_dir / "basic" / f"daily_basic_{ts_code}_{clean_date(start_date)}_{clean_date(end_date)}.csv"
        df = self._cached_call(
            path,
            self.pro.daily_basic,
            overwrite=overwrite,
            ts_code=ts_code,
            start_date=clean_date(start_date),
            end_date=clean_date(end_date),
            fields="ts_code,trade_date,close,turnover_rate,volume_ratio,pe,pb,ps,dv_ratio,total_mv,circ_mv",
        )
        return to_datetime_index(df)

    def moneyflow(self, ts_code: str, start_date: str, end_date: str, overwrite: bool = False) -> pd.DataFrame:
        path = self.data_dir / "moneyflow" / f"moneyflow_{ts_code}_{clean_date(start_date)}_{clean_date(end_date)}.csv"
        df = self._cached_call(path, self.pro.moneyflow, overwrite=overwrite, ts_code=ts_code,
                               start_date=clean_date(start_date), end_date=clean_date(end_date))
        return to_datetime_index(df)

    def income(self, ts_code: str, start_date: str, end_date: str, overwrite: bool = False) -> pd.DataFrame:
        path = self.data_dir / "financial" / f"income_{ts_code}_{clean_date(start_date)}_{clean_date(end_date)}.csv"
        df = self._cached_call(path, self.pro.income, overwrite=overwrite, ts_code=ts_code,
                               start_date=clean_date(start_date), end_date=clean_date(end_date))
        for column in ("ann_date", "f_ann_date", "end_date"):
            if column in df:
                df[column] = pd.to_datetime(df[column].astype(str), format="%Y%m%d", errors="coerce")
        return df
