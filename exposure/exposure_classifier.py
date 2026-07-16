from __future__ import annotations

from pathlib import Path
import pandas as pd
import yaml


ALLOWED_EXPOSURE_TYPES = {
    "DIRECT_PRICE",
    "MARGIN",
    "DEMAND",
    "CAPEX",
    "SUBSTITUTION",
    "SHARED_MACRO",
    "UNKNOWN",
}


class CycleExposureClassifier:
    """
    Classify how a theme cycle may affect a candidate stock.

    This module does NOT decide whether a company is good.
    It describes the economic transmission path.

    Example:
        copper -> Jiangxi Copper: DIRECT_PRICE
        copper -> JCHX Mining: CAPEX
        copper -> lead/zinc stock: SHARED_MACRO
    """

    def __init__(
        self,
        rules_path: str | Path = "config/exposure_rules.yaml",
        manual_override_path: str | Path = "config/exposure_manual_override.csv",
    ):
        self.rules_path = Path(rules_path)
        self.manual_override_path = Path(manual_override_path)

        with open(self.rules_path, "r", encoding="utf-8") as f:
            self.rules = yaml.safe_load(f)

        self.default_type = self.rules.get("default_exposure_type", "UNKNOWN")
        self.manual = self._load_manual_override()

    def _load_manual_override(self) -> pd.DataFrame:
        if not self.manual_override_path.exists():
            return pd.DataFrame(
                columns=["ts_code", "theme", "exposure_type", "confidence", "reason"]
            )

        df = pd.read_csv(self.manual_override_path)

        if "confidence" not in df.columns:
            df["confidence"] = 1.0

        return df

    @staticmethod
    def _contains_any(text: str, keywords: list[str]) -> bool:
        text = "" if pd.isna(text) else str(text)
        return any(str(k) in text for k in keywords)

    def _manual_match(self, ts_code: str, theme: str):
        if self.manual.empty:
            return None

        m = self.manual[
            (self.manual["ts_code"].astype(str) == str(ts_code))
            & (self.manual["theme"].astype(str) == str(theme))
        ]

        if m.empty:
            return None

        row = m.iloc[0]
        exposure_type = str(row["exposure_type"])

        if exposure_type not in ALLOWED_EXPOSURE_TYPES:
            exposure_type = "UNKNOWN"

        return {
            "exposure_type": exposure_type,
            "exposure_confidence": float(row.get("confidence", 1.0)),
            "exposure_source": "MANUAL_OVERRIDE",
            "exposure_reason": row.get("reason", ""),
        }

    def _rule_match(self, row: pd.Series):
        theme = str(row.get("theme", ""))
        name = str(row.get("name", ""))
        industry = str(row.get("industry", ""))

        theme_rules = self.rules.get("rules", {}).get(theme, {})

        # Priority follows YAML order.
        for exposure_type, rule in theme_rules.items():
            if exposure_type not in ALLOWED_EXPOSURE_TYPES:
                continue

            industries = rule.get("industries", []) or []
            keywords = rule.get("name_keywords", []) or []

            industry_match = industry in industries if industries else False
            keyword_match = self._contains_any(name, keywords) if keywords else False

            if industry_match or keyword_match:
                return {
                    "exposure_type": exposure_type,
                    "exposure_confidence": 0.60,
                    "exposure_source": "RULE",
                    "exposure_reason": f"matched industry/name rule: industry={industry}, name={name}",
                }

        return {
            "exposure_type": self.default_type,
            "exposure_confidence": 0.0,
            "exposure_source": "UNCLASSIFIED",
            "exposure_reason": "no rule matched",
        }

    def classify_row(self, row: pd.Series) -> dict:
        manual = self._manual_match(row.get("ts_code"), row.get("theme"))

        if manual is not None:
            return manual

        return self._rule_match(row)

    def classify(self, candidates: pd.DataFrame) -> pd.DataFrame:
        if candidates.empty:
            return candidates

        rows = []

        for _, row in candidates.iterrows():
            result = self.classify_row(row)
            out = row.to_dict()
            out.update(result)
            rows.append(out)

        df = pd.DataFrame(rows)

        return df
