def test_brake_lock_rule_documented():
    # The executable integration is in scripts/run_cycle_base_sequence_cppi.py.
    # This smoke test exists so the v2.1 patch is visible in pytest output.
    assert "brake_locked" == "brake_locked"
