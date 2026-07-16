import pandas as pd

from risk.risk_exit import RiskExitEngine, apply_position_action


def series(values):
    return pd.Series(values, index=pd.date_range("2025-01-01", periods=len(values)))


def test_hard_drawdown_exits():
    engine = RiskExitEngine(min_history=60)
    prices = series(list(range(100, 180)) + [125])
    result = engine.evaluate_series(prices)
    assert result["risk_exit_status"] == "EXIT"
    assert "PEAK_DRAWDOWN" in result["risk_exit_reason"]


def test_soft_drawdown_reduces():
    engine = RiskExitEngine(min_history=60)
    prices = series(list(range(100, 180)) + [150])
    result = engine.evaluate_series(prices)
    assert result["risk_exit_status"] == "REDUCE"


def test_healthy_price_holds():
    engine = RiskExitEngine(min_history=60)
    prices = series(list(range(100, 181)))
    result = engine.evaluate_series(prices)
    assert result["risk_exit_status"] == "HOLD"


def test_exit_overrides_harvesting():
    df = pd.DataFrame(
        [
            {
                "risk_exit_status": "EXIT",
                "final_bucket": "FINAL_CANDIDATE",
                "fundamental_direction": "HARVESTING",
            }
        ]
    )
    out = apply_position_action(df)
    assert out.loc[0, "position_action"] == "EXIT"
