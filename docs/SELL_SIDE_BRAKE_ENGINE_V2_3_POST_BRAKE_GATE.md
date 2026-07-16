# Sell-Side Brake Engine v2.3: Post-Brake Re-Expansion Gate

This patch fixes the incorrect v2.2 global stage gate.

## Principle

Normal first expansion and normal step-add are untouched.

The cycle-stage gate is activated **only after** a real sell-side brake has fired:

```text
TREND_BRAKE or FULL_BRAKE
→ post_brake = True
```

After `post_brake = True`, any new `STEP_ADD` attempt must pass the regime gate.

## Allow Re-Expansion

```text
BOTTOM_RECOVERY
EARLY_STABILIZING
STABILIZING
EXPANSION
```

## Block Re-Expansion

```text
NEUTRAL
CONTRACTION
LATE_CYCLE
DEEP_BOTTOM_FALLING
UNKNOWN
```

If the old step-add price condition is true but the stage blocks re-expansion, the trade log records:

```text
STEP_ADD_BLOCKED_POST_BRAKE_STAGE
```

## Why

This keeps the original bottom-volume / accumulation / CPPI / step-add logic intact,
but prevents the strategy from doing:

```text
FULL_BRAKE
↓
late-cycle rebound
↓
automatic STEP_ADD
```
