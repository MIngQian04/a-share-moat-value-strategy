from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import numpy as np
import pandas as pd


@dataclass
class ComplementConfig:
    top_n_per_cycle_asset: int = 10
    min_obs: int = 120
    downside_quantile: float = 0.20
    min_defensive_candidates: int = 5
    weights: dict[str, float] | None = None

    def __post_init__(self) -> None:
        if self.weights is None:
            self.weights = {
                "downside_diversification_score": 0.30,
                "stress_return_score": 0.25,
                "drawdown_overlap_score": 0.20,
                "volatility_offset_score": 0.15,
                "valuation_score": 0.10,
            }


class ComplementaryAssetEngine:
    """
    Pair Allocation layer.

    Input:
    - final cycle candidates, normally data/processed/selection/final_candidates.csv
    - stock_return_matrix.csv
    - optional security master and valuation/context files

    Output:
    - for every cycle theme Rank 1, rank stocks that can act as complementary assets
    - the score focuses on what happens when the cycle asset is weak, not on simple full-sample correlation
    """

    DEFENSIVE_INDUSTRY_KEYWORDS = [
        "银行", "证券", "保险", "多元金融", "电力", "水务", "燃气", "供气", "供水",
        "公路", "铁路", "港口", "机场", "运营商", "通信运营", "白酒", "食品饮料",
        "饮料", "家用电器", "医药", "中药", "高速", "公用事业",
    ]

    def __init__(self, config: ComplementConfig | None = None):
        self.config = config or ComplementConfig()

    @staticmethod
    def _max_drawdown(r: pd.Series) -> float:
        r = pd.to_numeric(r, errors="coerce").dropna()
        if r.empty:
            return np.nan
        wealth = (1.0 + r).cumprod()
        peak = wealth.cummax()
        dd = wealth / peak - 1.0
        return float(dd.min())

    @staticmethod
    def _safe_corr(a: pd.Series, b: pd.Series) -> float:
        x = pd.concat([a, b], axis=1).dropna()
        if len(x) < 3 or x.iloc[:, 0].std() == 0 or x.iloc[:, 1].std() == 0:
            return np.nan
        return float(x.iloc[:, 0].corr(x.iloc[:, 1]))

    @staticmethod
    def _scale_series(s: pd.Series, higher_is_better: bool = True) -> pd.Series:
        x = pd.to_numeric(s, errors="coerce")
        if x.notna().sum() == 0:
            return pd.Series(np.nan, index=s.index)
        pct = x.rank(pct=True, method="average", ascending=not higher_is_better) * 100.0
        return pct

    def _prepare_returns(self, returns: pd.DataFrame) -> pd.DataFrame:
        out = returns.copy()
        if "trade_date" not in out.columns:
            raise ValueError("return matrix must contain trade_date")
        out["trade_date"] = pd.to_datetime(out["trade_date"])
        out = out.sort_values("trade_date").set_index("trade_date")
        return out.apply(pd.to_numeric, errors="coerce")

    def _cycle_rank1(self, final_candidates: pd.DataFrame) -> pd.DataFrame:
        fc = final_candidates.copy()
        if "assembly_rank" not in fc.columns:
            raise ValueError("final_candidates must contain assembly_rank")
        fc["assembly_rank"] = pd.to_numeric(fc["assembly_rank"], errors="coerce")
        if "final_bucket" in fc.columns:
            fc = fc[fc["final_bucket"].astype(str).eq("FINAL_CANDIDATE")]
        rank1 = fc[fc["assembly_rank"].eq(1)].copy()
        if rank1.empty:
            rank1 = fc.sort_values(["theme", "assembly_rank"]).groupby("theme").head(1).copy()
        return rank1

    def _candidate_universe(
        self,
        returns_wide: pd.DataFrame,
        security_master: pd.DataFrame | None,
        cycle_codes: set[str],
    ) -> pd.DataFrame:
        available = [c for c in returns_wide.columns if c not in cycle_codes]
        base = pd.DataFrame({"ts_code": available})
        if security_master is not None and not security_master.empty:
            keep = [c for c in ["ts_code", "name", "industry", "market", "list_status"] if c in security_master.columns]
            base = base.merge(security_master[keep].drop_duplicates("ts_code"), on="ts_code", how="left")
        else:
            base["name"] = np.nan
            base["industry"] = np.nan

        industry = base.get("industry", pd.Series("", index=base.index)).fillna("").astype(str)
        is_defensive = industry.apply(
            lambda x: any(keyword in x for keyword in self.DEFENSIVE_INDUSTRY_KEYWORDS)
        )
        base["candidate_type"] = np.where(is_defensive, "DEFENSIVE_INDUSTRY", "NON_CYCLE_FALLBACK")

        defensive_count = int(is_defensive.sum())
        if defensive_count >= self.config.min_defensive_candidates:
            return base[is_defensive].copy()
        # In small research datasets the return matrix may only contain current-cycle candidates.
        # Fallback keeps the module runnable and clearly labels that candidates are not a true defensive pool.
        return base.copy()

    def _valuation_context(
        self,
        candidates: pd.DataFrame,
        optional_valuation: pd.DataFrame | None,
    ) -> pd.DataFrame:
        out = candidates.copy()
        out["valuation_score"] = 50.0
        out["valuation_status"] = "NEUTRAL_MISSING_VALUATION"
        if optional_valuation is None or optional_valuation.empty or "ts_code" not in optional_valuation.columns:
            return out

        val = optional_valuation.copy()
        cols = ["ts_code"] + [c for c in ["pb_percentile", "valuation_score", "valuation_status", "valuation_context"] if c in val.columns]
        val = val[cols].drop_duplicates("ts_code")
        out = out.merge(val, on="ts_code", how="left", suffixes=("", "_raw"))

        if "valuation_score_raw" in out.columns:
            raw = pd.to_numeric(out["valuation_score_raw"], errors="coerce")
            out["valuation_score"] = raw.fillna(out["valuation_score"])
            out["valuation_status"] = np.where(raw.notna(), "FROM_VALUATION_SCORE", out["valuation_status"])
        elif "pb_percentile" in out.columns:
            # Lower PB percentile is treated as more attractive for defensive / financial assets.
            pb = pd.to_numeric(out["pb_percentile"], errors="coerce")
            out["valuation_score"] = (100.0 - pb).fillna(out["valuation_score"])
            out["valuation_status"] = np.where(pb.notna(), "FROM_LOW_PB_PERCENTILE", out["valuation_status"])
        return out

    def _score_one_pair(self, cycle_ret: pd.Series, candidate_ret: pd.Series) -> dict[str, float]:
        pair = pd.concat([cycle_ret, candidate_ret], axis=1, keys=["cycle", "candidate"]).dropna()
        if len(pair) < self.config.min_obs:
            return {"n_obs": len(pair)}

        cycle = pair["cycle"]
        cand = pair["candidate"]
        threshold = cycle.quantile(self.config.downside_quantile)
        stress = pair[cycle <= threshold]

        cycle_dd = (1.0 + cycle).cumprod() / (1.0 + cycle).cumprod().cummax() - 1.0
        cand_dd = (1.0 + cand).cumprod() / (1.0 + cand).cumprod().cummax() - 1.0
        cycle_dd_flag = cycle_dd <= cycle_dd.quantile(0.20)
        cand_dd_flag = cand_dd <= cand_dd.quantile(0.20)

        return {
            "n_obs": len(pair),
            "full_corr": self._safe_corr(cycle, cand),
            "downside_corr": self._safe_corr(stress["cycle"], stress["candidate"]),
            "stress_return": float(stress["candidate"].mean()) if not stress.empty else np.nan,
            "cycle_stress_return": float(stress["cycle"].mean()) if not stress.empty else np.nan,
            "drawdown_overlap": float((cycle_dd_flag & cand_dd_flag).mean()),
            "cycle_ann_vol": float(cycle.std() * np.sqrt(252.0)),
            "candidate_ann_vol": float(cand.std() * np.sqrt(252.0)),
            "cycle_max_drawdown": self._max_drawdown(cycle),
            "candidate_max_drawdown": self._max_drawdown(cand),
            "candidate_ann_return": float((1.0 + cand.mean()) ** 252 - 1.0),
        }

    def build(
        self,
        final_candidates: pd.DataFrame,
        returns: pd.DataFrame,
        security_master: pd.DataFrame | None = None,
        optional_valuation: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        returns_wide = self._prepare_returns(returns)
        rank1 = self._cycle_rank1(final_candidates)
        cycle_codes = set(rank1["ts_code"].dropna().astype(str))
        candidates = self._candidate_universe(returns_wide, security_master, cycle_codes)
        candidates = self._valuation_context(candidates, optional_valuation)

        rows: list[dict] = []
        for _, leader in rank1.iterrows():
            cycle_code = str(leader["ts_code"])
            if cycle_code not in returns_wide.columns:
                continue
            cycle_ret = returns_wide[cycle_code]
            for _, cand in candidates.iterrows():
                cand_code = str(cand["ts_code"])
                if cand_code == cycle_code or cand_code not in returns_wide.columns:
                    continue
                metrics = self._score_one_pair(cycle_ret, returns_wide[cand_code])
                if metrics.get("n_obs", 0) < self.config.min_obs:
                    continue
                rows.append(
                    {
                        "theme": leader.get("theme"),
                        "cycle_ts_code": cycle_code,
                        "cycle_name": leader.get("name", np.nan),
                        "cycle_assembly_rank": leader.get("assembly_rank", np.nan),
                        "candidate_ts_code": cand_code,
                        "candidate_name": cand.get("name", np.nan),
                        "candidate_industry": cand.get("industry", np.nan),
                        "candidate_type": cand.get("candidate_type", np.nan),
                        "valuation_score": cand.get("valuation_score", np.nan),
                        "valuation_status": cand.get("valuation_status", np.nan),
                        **metrics,
                    }
                )

        result = pd.DataFrame(rows)
        if result.empty:
            return result

        result["downside_diversification_score"] = result.groupby("theme")["downside_corr"].transform(
            lambda s: self._scale_series(-s, higher_is_better=True)
        )
        result["stress_return_score"] = result.groupby("theme")["stress_return"].transform(
            lambda s: self._scale_series(s, higher_is_better=True)
        )
        result["drawdown_overlap_score"] = result.groupby("theme")["drawdown_overlap"].transform(
            lambda s: self._scale_series(-s, higher_is_better=True)
        )
        result["volatility_offset_raw"] = result["cycle_ann_vol"] - result["candidate_ann_vol"]
        result["volatility_offset_score"] = result.groupby("theme")["volatility_offset_raw"].transform(
            lambda s: self._scale_series(s, higher_is_better=True)
        )

        result["complement_score"] = 0.0
        for col, weight in self.config.weights.items():
            if col in result.columns:
                result["complement_score"] += pd.to_numeric(result[col], errors="coerce").fillna(50.0) * weight

        result["pair_rank"] = result.groupby("theme")["complement_score"].rank(method="dense", ascending=False)
        result = result.sort_values(["theme", "pair_rank", "complement_score"], ascending=[True, True, False])
        return result[result["pair_rank"] <= self.config.top_n_per_cycle_asset].reset_index(drop=True)
