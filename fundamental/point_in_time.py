from __future__ import annotations

from pathlib import Path
import pandas as pd


class FinancialPointInTimeStore:
    """
    Read cached financial statements and select latest available rows.

    Point-in-time rule:
        ann_date <= decision_date

    Comparable previous statement:
        same quarter in previous year if available.
    """

    def __init__(
        self,
        raw_dir: str | Path = "data/raw/fundamental",
    ):
        self.raw_dir = Path(raw_dir)

    def _path(self, endpoint: str, ts_code: str) -> Path:
        safe_code = ts_code.replace(".", "_")
        return self.raw_dir / endpoint / f"{safe_code}.parquet"

    def read_endpoint(self, endpoint: str, ts_code: str) -> pd.DataFrame:
        path = self._path(endpoint, ts_code)

        if not path.exists():
            return pd.DataFrame()

        df = pd.read_parquet(path)

        if df.empty:
            return df

        for col in ["ann_date", "end_date"]:
            if col in df.columns:
                df[col] = df[col].astype(str)

        return df

    @staticmethod
    def latest_available(df: pd.DataFrame, decision_date: str) -> pd.Series | None:
        if df.empty or "ann_date" not in df.columns or "end_date" not in df.columns:
            return None

        available = df[df["ann_date"].astype(str) <= decision_date].copy()

        if available.empty:
            return None

        available = available.sort_values(
            ["end_date", "ann_date"],
            ascending=[False, False],
        )

        return available.iloc[0]

    @staticmethod
    def comparable_previous(df: pd.DataFrame, current_end_date: str) -> pd.Series | None:
        if df.empty or "end_date" not in df.columns:
            return None

        end_date = str(current_end_date)
        if len(end_date) != 8:
            return None

        prev_year = str(int(end_date[:4]) - 1)
        comparable_end_date = prev_year + end_date[4:]

        prev = df[df["end_date"].astype(str) == comparable_end_date].copy()

        if prev.empty:
            # fallback: most recent earlier statement before current_end_date
            prev = df[df["end_date"].astype(str) < end_date].copy()

        if prev.empty:
            return None

        prev = prev.sort_values("end_date", ascending=False)
        return prev.iloc[0]

    def latest_statement_bundle(
        self,
        ts_code: str,
        decision_date: str,
    ) -> dict:
        bundle = {}

        for endpoint in [
            "balancesheet",
            "income",
            "cashflow",
            "fina_indicator",
        ]:
            df = self.read_endpoint(endpoint, ts_code)
            latest = self.latest_available(df, decision_date)

            if latest is None:
                bundle[endpoint] = None
                bundle[f"{endpoint}_prev"] = None
                continue

            prev = self.comparable_previous(df, latest["end_date"])

            bundle[endpoint] = latest
            bundle[f"{endpoint}_prev"] = prev

        return bundle
