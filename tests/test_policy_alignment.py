import pandas as pd

from selection.policy_alignment import apply_policy_alignment


def test_policy_requires_official_government_source():
    c = pd.DataFrame([{"ts_code": "A"}])
    m = pd.DataFrame([{"ts_code": "A", "policy_code": "P", "policy_explicitness": 5,
                       "company_exposure": 5, "profit_pool_fit": 5, "overcapacity_risk": 1}])
    p = pd.DataFrame([{"policy_code": "P", "policy_name": "x", "source_level": "NATIONAL_PLAN",
                       "official_source_url": "https://example.com", "official_wording": "x",
                       "classification_note": "x"}])
    assert apply_policy_alignment(c, m, p).iloc[0]["policy_status"] == "OUT_OF_POLICY_SCOPE"


def test_explicit_policy_does_not_override_weak_profit_pool():
    c = pd.DataFrame([{"ts_code": "A"}])
    m = pd.DataFrame([{"ts_code": "A", "policy_code": "P", "policy_explicitness": 5,
                       "company_exposure": 5, "profit_pool_fit": 2, "overcapacity_risk": 1}])
    p = pd.DataFrame([{"policy_code": "P", "policy_name": "x", "source_level": "NATIONAL_PLAN",
                       "official_source_url": "https://www.gov.cn/x", "official_wording": "x",
                       "classification_note": "x"}])
    assert apply_policy_alignment(c, m, p).iloc[0]["policy_status"] == "POLICY_WATCH"
