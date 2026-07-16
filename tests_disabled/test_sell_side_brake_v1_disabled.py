import pandas as pd

from brake.sell_side_brake import SellSideBrakeEngine


def make_series(values):
    return pd.Series(values, index=pd.date_range("2025-01-01", periods=len(values)))


def test_brake_can_only_reduce_exposure():
    assert SellSideBrakeEngine.apply_cap(0.20, 0.45) == 0.20
    assert SellSideBrakeEngine.apply_cap(0.70, 0.45) == 0.45
    assert SellSideBrakeEngine.apply_cap(0.70, 0.00) == 0.00


def test_close_below_ma40_full_brake():
    close = make_series([100.0] * 39 + [80.0])
    result = SellSideBrakeEngine().evaluate_series(close)
    assert result.brake_state == "FULL_BRAKE"
    assert result.brake_cap == 0.0


def test_close_below_ma20_above_ma40_trend_brake():
    # Long enough history; latest close is below MA20 but still above MA40.
    close = make_series([100.0] * 20 + [120.0] * 19 + [110.0])
    result = SellSideBrakeEngine().evaluate_series(close)
    assert result.brake_state == "TREND_BRAKE"
    assert result.brake_cap == 0.25


def test_top_volume_stagnation_early_brake():
    close = make_series(list(range(100, 160)) + [160, 160, 160, 160, 160])
    amount = make_series([100.0] * 60 + [300.0, 300.0, 300.0, 300.0, 300.0])
    result = SellSideBrakeEngine().evaluate_series(close, amount)
    assert result.brake_state == "EARLY_BRAKE"
    assert result.brake_cap == 0.45


def test_healthy_trend_brake_off():
    close = make_series(list(range(100, 170)))
    amount = make_series([100.0] * 70)
    result = SellSideBrakeEngine().evaluate_series(close, amount)
    assert result.brake_state == "OFF"
    assert result.brake_cap == 1.0
