from scripts.run_cycle_base_sequence_cppi import stage_allows_reexpansion

def test_real_recovery_regimes_allow_reexpansion():
    for regime in [
        "BOTTOM_RECOVERY",
        "EARLY_STABILIZING",
        "STABILIZING",
        "EXPANSION",
    ]:
        assert stage_allows_reexpansion(regime)

def test_real_bad_or_late_regimes_block_reexpansion():
    for regime in [
        "NEUTRAL",
        "CONTRACTION",
        "LATE_CYCLE",
        "DEEP_BOTTOM_FALLING",
        "UNKNOWN",
    ]:
        assert not stage_allows_reexpansion(regime)
