from __future__ import annotations

from dataclasses import dataclass
import numpy as np
import pandas as pd


@dataclass
class ComplementValuationConfig:
    min_obs: int = 120


class ComplementValuationEngine:
    """Valuation layer for complementary assets only.

    Scores each stock relative to its own history. Lower PE/PB percentile is
    more attractive; higher dividend-yield percentile is more attractive.
    The cycle Rank-1 assets are excluded by the runner before this engine is called.
    """

    BANK_KEYWORDS = ("银行",)
    BROKER_KEYWORDS = ("证券", "多元金融")
    CONSUMER_KEYWORDS = ("白酒", "食品饮料", "饮料")
    UTILITY_KEYWORDS = ("电力", "水务", "燃气", "供气", "供水", "公用事业", "高速", "公路")

    def __init__(self, config: ComplementValuationConfig | None = None):
        self.config = config or ComplementValuationConfig()

    @staticmethod
    def _contains(industry: str, keywords: tuple[str, ...]) -> bool:
        return any(k in str(industry) for k in keywords)

    @staticmethod
    def _latest_percentile(s: pd.Series) -> tuple[float, int]:
        x = pd.to_numeric(s, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
        if x.empty:
            return np.nan, 0
        latest = float(x.iloc[-1])
        pct = float((x <= latest).mean() * 100.0)
        return pct, len(x)

    def _route(self, industry: str) -> str:
        if self._contains(industry, self.BANK_KEYWORDS):
            return "BANK_PB"
        if self._contains(industry, self.BROKER_KEYWORDS):
            return "BROKER_PB"
        if self._contains(industry, self.CONSUMER_KEYWORDS):
            return "CONSUMER_PE"
        if self._contains(industry, self.UTILITY_KEYWORDS):
            return "UTILITY_DIVIDEND_PE"
        return "GENERIC_PE_PB"

    def build(self, daily_basic: pd.DataFrame, security_master: pd.DataFrame) -> pd.DataFrame:
        db = daily_basic.copy()
        sm = security_master.copy()
        db["trade_date"] = pd.to_datetime(db["trade_date"])
        db = db.sort_values(["ts_code", "trade_date"])
        keep = [c for c in ["ts_code", "name", "industry"] if c in sm.columns]
        meta = sm[keep].drop_duplicates("ts_code")
        db = db.merge(meta, on="ts_code", how="left")

        rows = []
        for code, g in db.groupby("ts_code", sort=False):
            industry = str(g["industry"].iloc[-1]) if "industry" in g.columns else ""
            name = g["name"].iloc[-1] if "name" in g.columns else np.nan
            model = self._route(industry)
            pe_pct, pe_n = self._latest_percentile(g["pe_ttm"]) if "pe_ttm" in g else (np.nan, 0)
            pb_pct, pb_n = self._latest_percentile(g["pb"]) if "pb" in g else (np.nan, 0)
            dv_pct, dv_n = self._latest_percentile(g["dv_ttm"]) if "dv_ttm" in g else (np.nan, 0)

            components = {}
            if model in ("BANK_PB", "BROKER_PB"):
                if pb_n >= self.config.min_obs:
                    components["low_pb_score"] = 100.0 - pb_pct
            elif model == "CONSUMER_PE":
                if pe_n >= self.config.min_obs:
                    components["low_pe_score"] = 100.0 - pe_pct
            elif model == "UTILITY_DIVIDEND_PE":
                if dv_n >= self.config.min_obs:
                    components["dividend_score"] = dv_pct
                if pe_n >= self.config.min_obs:
                    components["low_pe_score"] = 100.0 - pe_pct
            else:
                if pe_n >= self.config.min_obs:
                    components["low_pe_score"] = 100.0 - pe_pct
                if pb_n >= self.config.min_obs:
                    components["low_pb_score"] = 100.0 - pb_pct

            score = float(np.mean(list(components.values()))) if components else 50.0
            status = "VALUED" if components else "NEUTRAL_INSUFFICIENT_HISTORY"
            rows.append({
                "ts_code": code,
                "name": name,
                "industry": industry,
                "valuation_model": model,
                "pe_percentile": pe_pct,
                "pb_percentile": pb_pct,
                "dividend_yield_percentile": dv_pct,
                "valuation_score": score,
                "valuation_status": status,
                "valuation_components": "|".join(f"{k}={v:.2f}" for k, v in components.items()),
                "pe_obs": pe_n, "pb_obs": pb_n, "dividend_obs": dv_n,
            })
        return pd.DataFrame(rows).sort_values("valuation_score", ascending=False).reset_index(drop=True)
