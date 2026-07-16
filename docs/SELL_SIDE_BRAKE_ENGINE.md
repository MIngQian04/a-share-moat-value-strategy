# Sell-Side Brake Engine v1

This patch adds a sell-side brake overlay to the existing cycle allocation engine.
It does **not** change the original accumulation, CPPI, or step-add logic.

The brake engine only caps the exposure that the existing engine already wants to hold:

```text
final_cycle_exposure = min(cppi_or_step_add_target_exposure, brake_exposure_cap)
```

## Signals

| Signal | Meaning | Brake state | Exposure cap |
|---|---|---|---:|
| Close > MA20 and no top-volume warning | Trend is intact | OFF | 100% |
| Top volume stagnation | High-volume price stagnation after an advance | EARLY_BRAKE | 45% |
| Close < MA20 | Short/mid trend is damaged | TREND_BRAKE | 25% |
| Close < MA40 | Medium trend is broken | FULL_BRAKE | 0% |

## Top-volume stagnation definition

The first version defines top-volume stagnation as:

```text
5D average amount / 20D average amount >= 1.5
and price position in 60D range >= 70%
and 5D return <= 3%
```

It is an early warning only. It does not force a full exit.

## Design rule

The brake engine can only reduce exposure. It cannot create a buy/add signal.
