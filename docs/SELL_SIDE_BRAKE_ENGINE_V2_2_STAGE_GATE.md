# Sell-Side Brake Engine v2.2: Cycle-Stage Re-Expansion Gate

This patch removes the v2.1 permanent brake lock idea.

## Principle

- Existing bottom-volume / accumulation / CPPI / step-add logic stays unchanged.
- Sell-side brake still controls current exposure through MA5/20/40.
- Whether the strategy may **add risk again** is decided by cycle stage.

## Rule

Step Add is allowed only in upward/recovery regimes:

```text
BOTTOM_RECOVERY
ACCUMULATION
EARLY_UPTREND
EXPANSION
RECOVERING
```

Step Add is blocked in late or worsening regimes:

```text
HARVESTING
LATE_CYCLE
CONTRACTION
DEEP_BOTTOM_FALLING
DETERIORATING
```

If the original step-add price condition is true but the stage blocks it, the trade log records:

```text
STEP_ADD_BLOCKED_BY_STAGE
```

This solves the problem:

```text
FULL_BRAKE
↓
small rebound
↓
automatic STEP_ADD
```

without locking the strategy forever.
