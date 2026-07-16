# Sell-Side Brake Engine v2.1

This patch fixes a v2 issue:

> After `SELL_SIDE_BRAKE`, the strategy could later resume `STEP_ADD` automatically.

## New Rule

When either signal appears:

- `TREND_BRAKE`
- `FULL_BRAKE`

the strategy sets:

```text
brake_locked = True
```

While locked:

```text
risk_expansion_open = False
STEP_ADD is disabled
cycle exposure is capped by brake_lock_cap
```

The lock is released only when a new accumulation / sequence confirmation occurs, or when the theme fully exits and a new theme enters.

## Why

This prevents the strategy from doing:

```text
FULL_BRAKE
↓
small rebound
↓
STEP_ADD again
```

without a new bottom-volume or sequence confirmation.
