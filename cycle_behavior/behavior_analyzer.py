from __future__ import annotations

import numpy as np
import pandas as pd


class CycleBehaviorAnalyzer:
    """
    Cycle Behavior V2.

    After theme correlation retrieval, this module measures:
    1. Upside elasticity
    2. Downside elasticity
    3. Cycle convexity
    4. Multi-day lead score
    5. Multi-day lag score

    It avoids one synthetic total score.
    It outputs an interpretable behavior profile instead.
    """

    def __init__(
        self,
        stock_returns: pd.DataFrame,
        theme_returns: pd.DataFrame,
        min_obs: int = 120,
        lead_lag_window: int = 5,
        positive_theme_threshold: float = 0.0,
        negative_theme_threshold: float = 0.0,
    ):
        self.stock_returns = stock_returns.sort_index()
        self.theme_returns = theme_returns.sort_index()
        self.min_obs = min_obs
        self.lead_lag_window = lead_lag_window
        self.positive_theme_threshold = positive_theme_threshold
        self.negative_theme_threshold = negative_theme_threshold

    @staticmethod
    def _safe_ratio(num: float, den: float) -> float:
        if pd.isna(num) or pd.isna(den) or abs(den) < 1e-12:
            return np.nan
        return num / den

    @staticmethod
    def _forward_compound_return(r: pd.Series, window: int) -> pd.Series:
        """
        Forward compound return from t+1 to t+window.

        Example:
            window = 5
            output[t] = (1+r[t+1])...(1+r[t+5]) - 1
        """
        return (
            (1 + r)
            .shift(-1)
            .rolling(window)
            .apply(np.prod, raw=True)
            .shift(-(window - 1))
            - 1
        )

    def _elasticity(self, stock: pd.Series, theme: pd.Series) -> dict:
        pair = pd.concat([stock, theme], axis=1).dropna()
        pair.columns = ["stock", "theme"]

        if len(pair) < self.min_obs:
            return {
                "upside_elasticity": np.nan,
                "downside_elasticity": np.nan,
                "cycle_convexity": np.nan,
                "up_obs": 0,
                "down_obs": 0,
            }

        up = pair[pair["theme"] > self.positive_theme_threshold]
        down = pair[pair["theme"] < -self.negative_theme_threshold]

        if len(up) < 30 or len(down) < 30:
            return {
                "upside_elasticity": np.nan,
                "downside_elasticity": np.nan,
                "cycle_convexity": np.nan,
                "up_obs": len(up),
                "down_obs": len(down),
            }

        up_elasticity = self._safe_ratio(
            up["stock"].mean(),
            up["theme"].mean(),
        )

        down_elasticity = self._safe_ratio(
            abs(down["stock"].mean()),
            abs(down["theme"].mean()),
        )

        convexity = self._safe_ratio(
            up_elasticity,
            down_elasticity,
        )

        return {
            "upside_elasticity": up_elasticity,
            "downside_elasticity": down_elasticity,
            "cycle_convexity": convexity,
            "up_obs": len(up),
            "down_obs": len(down),
        }

    def _lead_lag(self, stock: pd.Series, theme: pd.Series) -> dict:
        pair = pd.concat([stock, theme], axis=1).dropna()
        pair.columns = ["stock", "theme"]

        if len(pair) < self.min_obs:
            return {
                "lead_score": np.nan,
                "lag_score": np.nan,
                "lead_lag_window": self.lead_lag_window,
            }

        theme_forward = self._forward_compound_return(
            pair["theme"],
            self.lead_lag_window,
        )

        stock_forward = self._forward_compound_return(
            pair["stock"],
            self.lead_lag_window,
        )

        # lead_score:
        # stock today vs future theme return.
        lead_pair = pd.concat(
            [pair["stock"], theme_forward],
            axis=1,
        ).dropna()

        # lag_score:
        # theme today vs future stock return.
        lag_pair = pd.concat(
            [pair["theme"], stock_forward],
            axis=1,
        ).dropna()

        lead = (
            lead_pair.iloc[:, 0].corr(lead_pair.iloc[:, 1])
            if len(lead_pair) >= self.min_obs - self.lead_lag_window
            else np.nan
        )

        lag = (
            lag_pair.iloc[:, 0].corr(lag_pair.iloc[:, 1])
            if len(lag_pair) >= self.min_obs - self.lead_lag_window
            else np.nan
        )

        return {
            "lead_score": lead,
            "lag_score": lag,
            "lead_lag_window": self.lead_lag_window,
        }

    @staticmethod
    def classify_elasticity(upside: float, downside: float, convexity: float) -> str:
        if pd.isna(upside) or pd.isna(downside) or pd.isna(convexity):
            return "UNKNOWN"

        if upside < 1.0:
            return "LOW_ELASTICITY"

        if upside >= 1.2 and convexity >= 1.2:
            return "HIGH_CONVEXITY"

        if upside >= 1.2 and convexity < 1.0:
            return "HIGH_BETA_HIGH_RISK"

        if upside >= 1.0 and convexity >= 1.15:
            return "BALANCED_CONVEXITY"

        return "ELASTIC"

    @staticmethod
    def classify_leadership(lead: float, lag: float) -> str:
        if pd.isna(lead) or pd.isna(lag):
            return "UNKNOWN"

        if lead > 0.10 and lead > lag + 0.03:
            return "LEADER"

        if lag > 0.10 and lag > lead + 0.03:
            return "FOLLOWER"

        return "CO_MOVER"

    def analyze_candidate(self, ts_code: str, theme: str) -> dict:
        if ts_code not in self.stock_returns.columns or theme not in self.theme_returns.columns:
            return {
                "upside_elasticity": np.nan,
                "downside_elasticity": np.nan,
                "cycle_convexity": np.nan,
                "lead_score": np.nan,
                "lag_score": np.nan,
                "lead_lag_window": self.lead_lag_window,
                "elasticity_class": "UNKNOWN",
                "leadership_class": "UNKNOWN",
                "cycle_behavior_profile": "UNKNOWN",
            }

        stock = self.stock_returns[ts_code]
        theme_r = self.theme_returns[theme]

        e = self._elasticity(stock, theme_r)
        ll = self._lead_lag(stock, theme_r)

        elasticity_class = self.classify_elasticity(
            e["upside_elasticity"],
            e["downside_elasticity"],
            e["cycle_convexity"],
        )

        leadership_class = self.classify_leadership(
            ll["lead_score"],
            ll["lag_score"],
        )

        return {
            **e,
            **ll,
            "elasticity_class": elasticity_class,
            "leadership_class": leadership_class,
            "cycle_behavior_profile": f"{elasticity_class}_{leadership_class}",
        }

    def analyze(self, candidates: pd.DataFrame) -> pd.DataFrame:
        rows = []

        for _, row in candidates.iterrows():
            ts_code = str(row["ts_code"])
            theme = str(row["theme"])

            out = row.to_dict()
            out.update(
                self.analyze_candidate(
                    ts_code=ts_code,
                    theme=theme,
                )
            )
            rows.append(out)

        return pd.DataFrame(rows)
