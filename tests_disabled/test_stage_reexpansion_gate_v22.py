from scripts.run_cycle_base_sequence_cppi import stage_allows_step_add

def test_real_upward_recovery_regimes_allow_step_add():
    for regime in [
        "BOTTOM_RECOVERY",
        "EARLY_STABILIZING",
        "STABILIZING",
        "EXPANSION",
    ]:
        assert stage_allows_step_add(regime)

def test_real_late_or_bad_regimes_block_step_add():
    for regime in [
        "NEUTRAL",
        "CONTRACTION",
        "LATE_CYCLE",
        "DEEP_BOTTOM_FALLING",
        "UNKNOWN",
    ]:
        assert not stage_allows_step_add(regime)
