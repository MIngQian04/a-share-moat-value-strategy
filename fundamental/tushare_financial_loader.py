from __future__ import annotations

from pathlib import Path
import time
import pandas as pd
from tqdm import tqdm


class TushareFinancialLoader:
    """
    Download and cache financial statement data from Tushare.

    This module only downloads raw data.
    It does not score companies.

    Required Tushare endpoints:
        - balancesheet
        - income
        - cashflow
        - fina_indicator
    """

    def __init__(
        self,
        pro,
        raw_dir: str | Path = "data/raw/fundamental",
        sleep_seconds: float = 0.25,
    ):
        self.pro = pro
        self.raw_dir = Path(raw_dir)
        self.sleep_seconds = sleep_seconds

        for endpoint in [
            "balancesheet",
            "income",
            "cashflow",
            "fina_indicator",
        ]:
            (self.raw_dir / endpoint).mkdir(parents=True, exist_ok=True)

    def _cache_path(self, endpoint: str, ts_code: str) -> Path:
        safe_code = ts_code.replace(".", "_")
        return self.raw_dir / endpoint / f"{safe_code}.parquet"

    def _download_endpoint(
        self,
        endpoint: str,
        ts_code: str,
        start_date: str,
        end_date: str,
        force: bool = False,
    ) -> pd.DataFrame:
        path = self._cache_path(endpoint, ts_code)

        if path.exists() and not force:
            return pd.read_parquet(path)

        func = getattr(self.pro, endpoint)

        df = func(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
        )

        if df is None:
            df = pd.DataFrame()

        df.to_parquet(path, index=False)

        time.sleep(self.sleep_seconds)

        return df

    def download_for_codes(
        self,
        codes: list[str],
        start_date: str = "20180101",
        end_date: str = "20261231",
        force: bool = False,
    ) -> dict[str, dict[str, int]]:
        report = {}

        endpoints = [
            "balancesheet",
            "income",
            "cashflow",
            "fina_indicator",
        ]

        for ts_code in tqdm(codes, desc="financial download"):
            report[ts_code] = {}

            for endpoint in endpoints:
                try:
                    df = self._download_endpoint(
                        endpoint=endpoint,
                        ts_code=ts_code,
                        start_date=start_date,
                        end_date=end_date,
                        force=force,
                    )
                    report[ts_code][endpoint] = len(df)
                except Exception as e:
                    report[ts_code][endpoint] = f"FAILED: {e}"

        return report
