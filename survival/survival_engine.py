from __future__ import annotations

import numpy as np
import pandas as pd


class SurvivalAssetCapacityEngine:
    """
    Survival layer for cyclical equities.

    Core question:
        If the cycle reverses, does the company still own enough productive
        capacity to participate in the recovery?

    This is NOT a traditional quality score.

    It separates:
        - financial stress
        - asset/capacity status

    Financial weakness alone is not an automatic rejection.
    Asset/capacity erosion is treated much more seriously.
    """

    def __init__(
        self,
        severe_percentile: float = 0.15,
        total_asset_decline_watch: float = -0.10,
        fixed_asset_decline_watch: float = -0.15,
        cip_decline_watch: float = -0.20,
        capex_to_assets_expansion: float = 0.03,
        asset_disposal_to_assets_watch: float = 0.05,
        asset_disposal_to_assets_severe: float = 0.10,
        disposal_to_capex_watch: float = 0.50,
        disposal_to_capex_severe: float = 1.00,
    ):
        self.severe_percentile = severe_percentile
        self.total_asset_decline_watch = total_asset_decline_watch
        self.fixed_asset_decline_watch = fixed_asset_decline_watch
        self.cip_decline_watch = cip_decline_watch
        self.capex_to_assets_expansion = capex_to_assets_expansion
        self.asset_disposal_to_assets_watch = asset_disposal_to_assets_watch
        self.asset_disposal_to_assets_severe = asset_disposal_to_assets_severe
        self.disposal_to_capex_watch = disposal_to_capex_watch
        self.disposal_to_capex_severe = disposal_to_capex_severe

    @staticmethod
    def _safe_div(num, den):
        if pd.isna(num) or pd.isna(den) or abs(den) < 1e-12:
            return np.nan
        return num / den

    @staticmethod
    def _growth(current, previous):
        if pd.isna(current) or pd.isna(previous) or abs(previous) < 1e-12:
            return np.nan
        return current / previous - 1.0

    def build_metrics(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()

        out["cash_to_short_debt"] = out.apply(
            lambda r: self._safe_div(r.get("cash"), r.get("short_debt")),
            axis=1,
        )
        out["interest_coverage"] = out.apply(
            lambda r: self._safe_div(r.get("ebit"), r.get("interest_expense")),
            axis=1,
        )
        out["ocf_to_debt"] = out.apply(
            lambda r: self._safe_div(r.get("operating_cash_flow"), r.get("total_debt")),
            axis=1,
        )

        out["total_assets_yoy"] = out.apply(
            lambda r: self._growth(r.get("total_assets"), r.get("total_assets_prev")),
            axis=1,
        )
        out["fixed_assets_yoy"] = out.apply(
            lambda r: self._growth(r.get("fixed_assets"), r.get("fixed_assets_prev")),
            axis=1,
        )
        out["construction_in_progress_yoy"] = out.apply(
            lambda r: self._growth(
                r.get("construction_in_progress"),
                r.get("construction_in_progress_prev"),
            ),
            axis=1,
        )
        out["revenue_yoy_calc"] = out.apply(
            lambda r: self._growth(r.get("revenue"), r.get("revenue_prev")),
            axis=1,
        )

        out["asset_disposal_to_assets"] = out.apply(
            lambda r: self._safe_div(
                r.get("cash_from_asset_disposals"),
                r.get("total_assets_prev"),
            ),
            axis=1,
        )

        out["capex_to_assets"] = out.apply(
            lambda r: self._safe_div(
                r.get("capex_cash_paid"),
                r.get("total_assets_prev"),
            ),
            axis=1,
        )

        out["asset_disposal_to_capex"] = out.apply(
            lambda r: self._safe_div(
                r.get("cash_from_asset_disposals"),
                r.get("capex_cash_paid"),
            ),
            axis=1,
        )

        return out

    def add_theme_relative_stress(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()

        for col in ["cash_to_short_debt", "interest_coverage", "ocf_to_debt"]:
            out[f"{col}_pct"] = (
                out.groupby("theme")[col]
                .rank(method="average", pct=True)
            )

        return out

    def classify_row(self, row: pd.Series) -> pd.Series:
        stress_flags = []
        capacity_flags = []

        # Theme-relative financial stress.
        if row.get("cash_to_short_debt_pct", 1.0) <= self.severe_percentile:
            stress_flags.append("LIQUIDITY_STRESS")

        if row.get("interest_coverage_pct", 1.0) <= self.severe_percentile:
            stress_flags.append("INTEREST_STRESS")

        if row.get("ocf_to_debt_pct", 1.0) <= self.severe_percentile:
            stress_flags.append("CASH_FLOW_STRESS")

        assets_yoy = row.get("total_assets_yoy")
        fixed_yoy = row.get("fixed_assets_yoy")
        cip_yoy = row.get("construction_in_progress_yoy")
        revenue_yoy = row.get("revenue_yoy_calc")
        disposal_assets = row.get("asset_disposal_to_assets")
        disposal_capex = row.get("asset_disposal_to_capex")
        capex_assets = row.get("capex_to_assets")

        # Expansion evidence: company is still investing in productive assets.
        expansion_evidence = False
        if pd.notna(capex_assets) and capex_assets >= self.capex_to_assets_expansion:
            expansion_evidence = True
            capacity_flags.append("CAPEX_EXPANSION")

        if pd.notna(cip_yoy) and cip_yoy > 0.20:
            expansion_evidence = True
            capacity_flags.append("CIP_EXPANSION")

        if pd.notna(fixed_yoy) and fixed_yoy > 0.10:
            expansion_evidence = True
            capacity_flags.append("FIXED_ASSET_EXPANSION")

        # Erosion evidence: productive base is shrinking.
        erosion_evidence = []

        if pd.notna(assets_yoy) and assets_yoy <= self.total_asset_decline_watch:
            erosion_evidence.append("TOTAL_ASSET_SHRINKAGE")

        if pd.notna(fixed_yoy) and fixed_yoy <= self.fixed_asset_decline_watch:
            erosion_evidence.append("FIXED_ASSET_SHRINKAGE")

        if pd.notna(cip_yoy) and cip_yoy <= self.cip_decline_watch:
            erosion_evidence.append("CIP_SHRINKAGE")

        material_disposal = False
        severe_disposal = False

        if pd.notna(disposal_assets) and disposal_assets >= self.asset_disposal_to_assets_watch:
            material_disposal = True
            erosion_evidence.append("MATERIAL_ASSET_DISPOSAL")

        if pd.notna(disposal_assets) and disposal_assets >= self.asset_disposal_to_assets_severe:
            severe_disposal = True

        if pd.notna(disposal_capex) and disposal_capex >= self.disposal_to_capex_watch:
            material_disposal = True
            erosion_evidence.append("DISPOSAL_HIGH_VS_CAPEX")

        if pd.notna(disposal_capex) and disposal_capex >= self.disposal_to_capex_severe:
            severe_disposal = True

        # Net capacity state.
        #
        # A company should not be classified as CAPACITY_EROSION just because it had
        # some asset disposal. If CAPEX/CIP/fixed assets are expanding, the company
        # may be recycling assets rather than selling its future.
        severe_capacity_erosion = (
            severe_disposal
            and not expansion_evidence
        )

        structural_capacity_loss = (
            (len(erosion_evidence) >= 2)
            and not expansion_evidence
        )

        operating_capacity_loss = (
            pd.notna(fixed_yoy)
            and fixed_yoy <= self.fixed_asset_decline_watch
            and pd.notna(revenue_yoy)
            and revenue_yoy < 0
            and not expansion_evidence
        )

        stress_count = len(stress_flags)

        if expansion_evidence and not severe_capacity_erosion:
            capacity_status = "CAPACITY_EXPANSION"
            cycle_participation = "PRESERVED"

        elif severe_capacity_erosion or structural_capacity_loss or operating_capacity_loss:
            capacity_status = "CAPACITY_EROSION"
            cycle_participation = "IMPAIRED"

        else:
            capacity_status = "CAPACITY_PRESERVED"
            cycle_participation = "PRESERVED"

        # Financial survival status.
        if capacity_status == "CAPACITY_EROSION":
            survival_status = "CAPACITY_EROSION"
            distress_type = "ASSET_EROSION"

        elif stress_count >= 3:
            survival_status = "DISTRESS"
            distress_type = "FINANCIAL_DISTRESS"

        elif stress_count >= 1:
            survival_status = "WATCH"
            distress_type = "FINANCIAL_STRESS" if stress_count >= 2 else "SINGLE_STRESS"

        else:
            survival_status = "SAFE"
            distress_type = "NONE"

        return pd.Series({
            "financial_stress_flags": "|".join(stress_flags),
            "capacity_flags": "|".join(capacity_flags),
            "asset_erosion_flags": "|".join(erosion_evidence),
            "financial_stress_count": stress_count,
            "asset_erosion_count": len(erosion_evidence),
            "capacity_status": capacity_status,
            "survival_status": survival_status,
            "distress_type": distress_type,
            "cycle_participation": cycle_participation,
        })

    def analyze(self, financials: pd.DataFrame) -> pd.DataFrame:
        out = self.build_metrics(financials)
        out = self.add_theme_relative_stress(out)
        classifications = out.apply(self.classify_row, axis=1)
        return pd.concat([out, classifications], axis=1)
