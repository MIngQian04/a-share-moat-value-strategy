import pandas as pd
from brake.sell_side_brake import SellSideBrakeEngine

def frames(values, amounts=None):
    idx = pd.date_range("2025-01-01", periods=len(values))
    close = pd.DataFrame({"copper": values}, index=idx)
    amount = pd.DataFrame({"copper": amounts or [100.0] * len(values)}, index=idx)
    return idx, close, amount

def test_bottom_below_ma40_is_not_sold_before_trend_armed():
    idx, close, amount = frames(list(range(100, 60, -1)) + [60.0] * 10)
    r = SellSideBrakeEngine().evaluate_until(idx[-1], "copper", close, amount, trend_armed_prev=False)
    assert r.brake_state == "DISABLED"
    assert r.brake_cap == 1.0

def test_uptrend_arms():
    idx, close, amount = frames(list(range(60, 110)))
    r = SellSideBrakeEngine().evaluate_until(idx[-1], "copper", close, amount, trend_armed_prev=False)
    assert r.trend_armed is True
    assert r.brake_state == "OFF"

def test_compression_after_armed_brakes():
    idx, close, amount = frames([100.0] * 50)
    r = SellSideBrakeEngine().evaluate_until(idx[-1], "copper", close, amount, trend_armed_prev=True)
    assert r.brake_state == "COMPRESSION_BRAKE"
    assert r.brake_cap == 0.45

def test_top_volume_alone_warning_only():
    values = list(range(60, 105)) + [105.0] * 5
    amounts = [100.0] * 45 + [300.0] * 5
    idx, close, amount = frames(values, amounts)
    r = SellSideBrakeEngine().evaluate_until(idx[-1], "copper", close, amount, trend_armed_prev=True)
    assert r.distribution_warning is True
    assert r.brake_state == "OFF"
    assert r.brake_cap == 1.0

def test_apply_cap_never_increases():
    e = SellSideBrakeEngine()
    assert e.apply_cap(0.20, 0.45) == 0.20
    assert e.apply_cap(0.60, 0.45) == 0.45
    assert e.apply_cap(0.60, 0.0) == 0.0
