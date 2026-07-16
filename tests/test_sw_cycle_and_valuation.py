import numpy as np
import pandas as pd

from industry.sw_cycle import build_industry_nav, classify_industry_cycle
from valuation.owner_earnings import conservative_dcf


def test_industry_nav_uses_constituent_median_return():
    close = pd.DataFrame({"A": [100, 110], "B": [100, 100], "C": [100, 90]}, index=pd.date_range("2024-01-01", periods=2))
    members = pd.DataFrame({"ts_code": ["A", "B", "C"], "l1_name": ["行业", "行业", "行业"]})
    nav = build_industry_nav(close, members)
    assert nav.iloc[-1, 0] == 1.0


def test_recovery_requires_price_and_trend_confirmation():
    s = pd.Series(np.r_[np.linspace(100, 60, 140), np.linspace(60, 85, 80)])
    result = classify_industry_cycle(s)
    assert result["cycle_state"] in {"RECOVERY", "EXPANSION"}


def test_dcf_rejects_negative_owner_earnings():
    assert np.isnan(conservative_dcf(-1, 10, 100))


def test_dcf_caps_growth_assumption():
    high = conservative_dcf(100, 0, 10, growth=0.50)
    capped = conservative_dcf(100, 0, 10, growth=0.06)
    assert high == capped
