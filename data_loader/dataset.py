from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml
from tqdm import tqdm

from data_loader.tushare_client import TushareClient
from data_loader.universe import build_a_share_universe


class DataLayer:
    """
    Project data layer.

    Responsibilities:
    1. Load config.
    2. Fetch/cache benchmark and industry proxy indices.
    3. Build stock universe.
    4. Fetch/cache stock daily data.
    5. Save processed return matrices for later factor/backtest modules.
    """

    def __init__(self, config_path: str = "config/config.yaml"):
        with open(config_path, "r", encoding="utf-8") as f:
            self.cfg = yaml.safe_load(f)

        self.data_dir = Path(self.cfg["project"]["data_dir"])
        self.raw_dir = self.data_dir / "raw"
        self.processed_dir = self.data_dir / "processed"
        self.processed_dir.mkdir(parents=True, exist_ok=True)

        self.client = TushareClient(data_dir=self.raw_dir)

    @property
    def start_date(self) -> str:
        return self.cfg["data"]["start_date"]

    @property
    def end_date(self) -> str:
        return self.cfg["data"]["end_date"]

    def fetch_indices(self) -> dict[str, pd.DataFrame]:
        overwrite = self.cfg["cache"]["overwrite"]
        out = {}
        for name, code in self.cfg["data"]["indices"].items():
            out[name] = self.client.index_daily(code, self.start_date, self.end_date, overwrite=overwrite)
        return out

    def build_universe(self) -> pd.DataFrame:
        stock_basic = self.client.stock_basic(overwrite=self.cfg["cache"]["overwrite"])
        ucfg = self.cfg["data"]["stock_universe"]
        universe = build_a_share_universe(
            stock_basic,
            end_date=self.end_date,
            exclude_prefixes=tuple(ucfg["exclude_prefixes"]),
            min_list_days=int(ucfg["min_list_days"]),
            max_stocks=int(ucfg["max_stocks"]) if ucfg["max_stocks"] else None,
        )
        universe.to_csv(self.processed_dir / "universe.csv", index=False, encoding="utf-8-sig")
        return universe

    def fetch_stock_daily_batch(self, universe: pd.DataFrame) -> dict[str, pd.DataFrame]:
        overwrite = self.cfg["cache"]["overwrite"]
        data = {}
        for code in tqdm(universe["ts_code"].tolist(), desc="Fetching stock daily"):
            try:
                df = self.client.stock_daily(code, self.start_date, self.end_date, overwrite=overwrite)
                if len(df) > 0:
                    data[code] = df
            except Exception as exc:
                print(f"[WARN] {code} failed: {exc}")
        return data

    @staticmethod
    def build_close_matrix(stock_daily: dict[str, pd.DataFrame]) -> pd.DataFrame:
        closes = {}
        for code, df in stock_daily.items():
            if "close" in df.columns:
                closes[code] = df["close"]
        return pd.DataFrame(closes).sort_index()

    @staticmethod
    def build_return_matrix(close: pd.DataFrame) -> pd.DataFrame:
        return close.pct_change(fill_method=None)

    def run_mvp(self):
        indices = self.fetch_indices()
        universe = self.build_universe()
        stock_daily = self.fetch_stock_daily_batch(universe)

        close = self.build_close_matrix(stock_daily)
        rets = self.build_return_matrix(close)

        close.to_csv(self.processed_dir / "stock_close_matrix.csv", encoding="utf-8-sig")
        rets.to_csv(self.processed_dir / "stock_return_matrix.csv", encoding="utf-8-sig")

        for name, df in indices.items():
            df.to_csv(self.processed_dir / f"index_{name}.csv", encoding="utf-8-sig")

        summary = {
            "n_indices": len(indices),
            "n_universe": len(universe),
            "n_stock_daily_success": len(stock_daily),
            "start_date": self.start_date,
            "end_date": self.end_date,
        }
        pd.Series(summary).to_csv(self.processed_dir / "data_summary.csv", header=False)
        return summary
