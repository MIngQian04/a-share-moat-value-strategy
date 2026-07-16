import numpy as np
import pandas as pd

from portfolio.rotation_signals import defensive_signal_table, price_volume_features, target_weights


def test_bottom_volume_requires_low_position_and_volume_confirmation():
    prices = pd.Series(np.r_[np.linspace(20, 10, 230), np.linspace(10, 12, 22)])
    volume = pd.Series(np.r_[np.full(247, 100.0), np.full(5, 170.0)])
    features = price_volume_features(prices, volume)
    assert features["bottom_volume"] is True
    assert features["signal_state"] in {"BOTTOM_BASE", "TREND_ADD"}


def test_defensive_name_requires_manual_moat_approval():
    basic = pd.DataFrame([{"ts_code": "000001.SZ", "dv_ratio": 4.0, "pb": 1.0}])
    watchlist = pd.DataFrame([{"ts_code": "000001.SZ", "name": "example", "moat_approved": "FALSE"}])
    assert defensive_signal_table(basic, watchlist).iloc[0]["defensive_status"] == "WATCH"


def test_no_defensive_approval_leaves_defensive_budget_as_cash():
    cycle = pd.DataFrame([{"ts_code": "000001.SZ", "signal_state": "BOTTOM_BASE"}])
    defensive = pd.DataFrame(columns=["defensive_status"])
    result = target_weights(cycle, defensive)
    assert result.attrs["cycle_weight"] == 0.15
    assert result.attrs["cash_weight"] == 0.85


def test_target_weights_limits_cycle_to_one_name_per_theme():
    cycle = pd.DataFrame([
        {"ts_code": "000001.SZ", "theme": "steel", "signal_state": "BOTTOM_BASE", "priority_score": 90},
        {"ts_code": "000002.SZ", "theme": "steel", "signal_state": "BOTTOM_BASE", "priority_score": 80},
    ])
    result = target_weights(cycle, pd.DataFrame(columns=["defensive_status"]))
    assert len(result) == 1
    assert result.iloc[0]["ts_code"] == "000001.SZ"
