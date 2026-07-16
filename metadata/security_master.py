from __future__ import annotations

from pathlib import Path
import pandas as pd


class SecurityMasterBuilder:
    """
    Build point-in-time security master.

    Output:
    - security_master.csv:
        ts_code, symbol, name, area, industry, market, list_date, delist_date, list_status
    - namechange_history.csv:
        historical name changes, useful for ST / *ST filtering later

    Important:
    We DO NOT delete delisted securities from history.
    Delisted names stay in security_master with delist_date.
    """

    def __init__(self, client, output_dir: str | Path = "data/processed/metadata"):
        self.client = client
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _stock_basic_by_status(self, status: str) -> pd.DataFrame:
        return self.client.pro.stock_basic(
            exchange="",
            list_status=status,
            fields="ts_code,symbol,name,area,industry,list_date,market",
        )

    def build_security_master(self) -> pd.DataFrame:
        listed = self._stock_basic_by_status("L")
        delisted = self._stock_basic_by_status("D")

        listed["list_status"] = "L"
        listed["delist_date"] = pd.NaT

        delisted["list_status"] = "D"
        # Some Tushare accounts may not expose delist_date in stock_basic fields.
        # We keep the column anyway and improve later if we add a dedicated delist endpoint/source.
        if "delist_date" not in delisted.columns:
            delisted["delist_date"] = pd.NaT

        master = pd.concat([listed, delisted], ignore_index=True)
        master["list_date"] = pd.to_datetime(master["list_date"], errors="coerce")
        master["delist_date"] = pd.to_datetime(master["delist_date"], errors="coerce")

        master = master.drop_duplicates("ts_code", keep="first")
        master = master.sort_values("ts_code").reset_index(drop=True)

        out = self.output_dir / "security_master.csv"
        master.to_csv(out, index=False, encoding="utf-8-sig")
        return master

    def build_namechange_history(self, master: pd.DataFrame | None = None) -> pd.DataFrame:
        """
        Tushare namechange is used to detect ST / *ST history.
        If endpoint permission is limited, the function saves an empty file instead of crashing.
        """
        try:
            df = self.client.pro.namechange(
                fields="ts_code,name,start_date,end_date,change_reason"
            )
            df["start_date"] = pd.to_datetime(df["start_date"], errors="coerce")
            df["end_date"] = pd.to_datetime(df["end_date"], errors="coerce")
        except Exception as exc:
            print(f"[WARN] namechange endpoint failed: {exc}")
            df = pd.DataFrame(columns=["ts_code", "name", "start_date", "end_date", "change_reason"])

        out = self.output_dir / "namechange_history.csv"
        df.to_csv(out, index=False, encoding="utf-8-sig")
        return df

    @staticmethod
    def is_alive_on(master: pd.DataFrame, date: str | pd.Timestamp) -> pd.Series:
        date = pd.to_datetime(date)
        listed = master["list_date"].le(date)
        not_delisted = master["delist_date"].isna() | master["delist_date"].gt(date)
        return listed & not_delisted

    @staticmethod
    def is_st_on(namechange: pd.DataFrame, date: str | pd.Timestamp) -> pd.Series:
        """
        Returns a boolean Series indexed by namechange rows, not by ts_code.
        Later we can aggregate this into a ts_code-level ST status table.
        """
        if namechange.empty:
            return pd.Series([], dtype=bool)

        date = pd.to_datetime(date)
        start_ok = namechange["start_date"].le(date)
        end_ok = namechange["end_date"].isna() | namechange["end_date"].ge(date)
        name_has_st = namechange["name"].astype(str).str.contains("ST", case=False, na=False)
        reason_has_st = namechange["change_reason"].astype(str).str.contains("ST", case=False, na=False)
        return start_ok & end_ok & (name_has_st | reason_has_st)

    def build_point_in_time_universe(
        self,
        master: pd.DataFrame,
        as_of_date: str,
        exclude_st: bool = True,
        namechange: pd.DataFrame | None = None,
        min_list_days: int = 180,
        exclude_prefixes=("83", "87", "92"),
    ) -> pd.DataFrame:
        date = pd.to_datetime(as_of_date)
        df = master[self.is_alive_on(master, date)].copy()

        for prefix in exclude_prefixes:
            df = df[~df["ts_code"].astype(str).str.startswith(prefix)]

        df["list_days"] = (date - df["list_date"]).dt.days
        df = df[df["list_days"] >= min_list_days]

        if exclude_st and namechange is not None and not namechange.empty:
            st_rows = namechange[self.is_st_on(namechange, date)]
            st_codes = set(st_rows["ts_code"].dropna().astype(str))
            df = df[~df["ts_code"].isin(st_codes)]

        return df.sort_values("ts_code").reset_index(drop=True)
