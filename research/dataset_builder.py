from __future__ import annotations

from pathlib import Path
import pandas as pd

from data_loader.market_store import MarketStore
from metadata.security_master import SecurityMasterBuilder


class ResearchDatasetBuilder:
    """
    Convert raw daily parquet snapshots into research matrices:
    close, volume, amount, return, tradable_mask.

    The mask is point-in-time:
    - listed by the date
    - not delisted by the date
    - has price
    - has positive volume
    """

    def __init__(
        self,
        market_store: MarketStore,
        security_master_path: str | Path = "data/processed/metadata/security_master.csv",
        output_dir: str | Path = "data/processed/research",
    ):
        self.store = market_store
        self.security_master = pd.read_csv(security_master_path)
        self.security_master["list_date"] = pd.to_datetime(self.security_master["list_date"], errors="coerce")
        self.security_master["delist_date"] = pd.to_datetime(self.security_master["delist_date"], errors="coerce")
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def matrix(self, field: str, start_date=None, end_date=None) -> pd.DataFrame:
        return self.store.matrix(field, start_date=start_date, end_date=end_date)

    def tradable_mask(self, close: pd.DataFrame, volume: pd.DataFrame) -> pd.DataFrame:
        mask = close.notna() & volume.gt(0)

        for date in mask.index:
            alive = SecurityMasterBuilder.is_alive_on(self.security_master, date)
            alive_codes = set(self.security_master.loc[alive, "ts_code"].astype(str))
            mask.loc[date] = mask.loc[date] & mask.columns.to_series().isin(alive_codes).values

        return mask

    def build(self, start_date=None, end_date=None) -> dict[str, pd.DataFrame]:
        close = self.matrix("close", start_date, end_date)
        volume = self.matrix("vol", start_date, end_date)
        amount = self.matrix("amount", start_date, end_date)
        returns = close.pct_change(fill_method=None)
        mask = self.tradable_mask(close, volume)

        close.to_parquet(self.output_dir / "close.parquet")
        volume.to_parquet(self.output_dir / "volume.parquet")
        amount.to_parquet(self.output_dir / "amount.parquet")
        returns.to_parquet(self.output_dir / "returns.parquet")
        mask.to_parquet(self.output_dir / "tradable_mask.parquet")

        return {
            "close": close,
            "volume": volume,
            "amount": amount,
            "returns": returns,
            "tradable_mask": mask,
        }
