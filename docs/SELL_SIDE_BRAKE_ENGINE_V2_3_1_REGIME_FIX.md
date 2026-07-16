# Sell-Side Brake Engine v2.3.1: Current Theme Regime Fix

v2.3 had the correct architecture but passed the whole regime table into the re-expansion gate.

This patch adds:

```python
get_current_theme_regime(regime, dt, current_theme)
```

Then `STEP_ADD` after a brake uses the actual current theme's `theme_regime` string, such as:

```text
EXPANSION
BOTTOM_RECOVERY
LATE_CYCLE
CONTRACTION
```

instead of a full DataFrame.
