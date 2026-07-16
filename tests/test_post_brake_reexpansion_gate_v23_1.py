import pandas as pd
from scripts.run_cycle_base_sequence_cppi import (
    stage_allows_reexpansion,
    get_current_theme_regime,
)

def test_get_current_theme_regime_returns_string_not_dataframe():
    idx = pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2025-01-01"), "coal")],
        names=["trade_date", "theme"],
    )
    df = pd.DataFrame({"theme_regime": ["EXPANSION"]}, index=idx)
    assert get_current_theme_regime(df, pd.Timestamp("2025-01-01"), "coal") == "EXPANSION"

def test_reexpansion_gate_uses_real_regime_values():
    assert stage_allows_reexpansion("EXPANSION")
    assert stage_allows_reexpansion("BOTTOM_RECOVERY")
    assert not stage_allows_reexpansion("LATE_CYCLE")
    assert not stage_allows_reexpansion("CONTRACTION")
