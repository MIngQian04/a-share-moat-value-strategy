# Sell-Side Brake Engine v2

The existing accumulation, CPPI, exposure and step-add logic is unchanged.

Brake is disabled until the current position has established `MA5 > MA20 > MA40`.

After trend arming:
- MA5/MA20/MA40 compression <= 3%: cap 45%.
- Compression + top-volume stagnation warning: cap 35%.
- Close below MA20: cap 25%.
- Close below MA40: cap 0%.

Top-volume stagnation alone is warning-only.

Final cycle exposure is `min(original_cppi_exposure, brake_cap)`, so the brake can never increase exposure.
