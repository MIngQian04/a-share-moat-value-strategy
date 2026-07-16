from __future__ import annotations

import numpy as np
import pandas as pd


POLICY_SCORE_COLUMNS = ["policy_explicitness", "company_exposure", "profit_pool_fit", "overcapacity_risk"]


def apply_policy_alignment(candidates: pd.DataFrame, mapping: pd.DataFrame,
                           priorities: pd.DataFrame) -> pd.DataFrame:
    """Apply a reproducible national-policy gate before valuation and timing.

    Policy selects the research universe, not the security. Only national-plan
    rows with a government source can qualify. Company exposure and profit-pool
    capture remain separate because public spending can coexist with poor ROIC.
    """
    map_required = {"ts_code", "policy_code", *POLICY_SCORE_COLUMNS}
    priority_required = {"policy_code", "policy_name", "source_level", "official_source_url",
                         "official_wording", "classification_note"}
    if missing := map_required - set(mapping.columns):
        raise ValueError(f"policy mapping missing columns: {sorted(missing)}")
    if missing := priority_required - set(priorities.columns):
        raise ValueError(f"policy priorities missing columns: {sorted(missing)}")
    joined = candidates.merge(mapping, on="ts_code", how="left").merge(
        priorities, on="policy_code", how="left"
    )
    for col in POLICY_SCORE_COLUMNS:
        joined[col] = pd.to_numeric(joined[col], errors="coerce")
    official = (joined["source_level"].eq("NATIONAL_PLAN")
                & joined["official_source_url"].astype(str).str.contains(r"gov\.cn", regex=True))
    explicitness = joined["policy_explicitness"]
    exposure = joined["company_exposure"]
    profit_fit = joined["profit_pool_fit"]
    capacity_quality = 6 - joined["overcapacity_risk"]
    joined["policy_alignment_score"] = 100 * (
        0.30 * (explicitness - 1) / 4
        + 0.30 * (exposure - 1) / 4
        + 0.25 * (profit_fit - 1) / 4
        + 0.15 * (capacity_quality - 1) / 4
    )
    joined["policy_status"] = np.select(
        [official & explicitness.ge(4) & exposure.ge(4) & profit_fit.ge(3),
         official & explicitness.ge(3) & exposure.ge(3)],
        ["POLICY_ELIGIBLE", "POLICY_WATCH"],
        default="OUT_OF_POLICY_SCOPE",
    )
    joined["policy_reason"] = np.select(
        [joined["policy_status"].eq("POLICY_ELIGIBLE"), joined["policy_status"].eq("POLICY_WATCH")],
        ["national plan is explicit; listed-company exposure and profit-pool fit pass",
         "national-plan direction exists but exposure or profit-pool capture needs evidence"],
        default="no qualifying national-plan mapping",
    )
    return joined
