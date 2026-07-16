# Reproducibility and Data Boundaries

The public repository does not include raw or processed market data. Tushare
data must be obtained under the provider's licence and regenerated locally.

## Current forward strategy

```bash
cp .env.example .env
# Fill TUSHARE_TOKEN locally when online access is required.

python3 scripts/refresh_rotation_market_data.py
python3 scripts/run_future_demand_screen.py --refresh-financials
python3 scripts/run_moat_radar.py
python3 scripts/run_barbell_strategy.py
```

Offline mode uses existing local caches and must report missing or unavailable
inputs explicitly:

```bash
python3 scripts/run_moat_radar.py --offline
python3 scripts/run_barbell_strategy.py --offline
```

The live portfolio ledger is forward-only. A weight selected from a completed
session may affect returns only from the next completed session onward.

## Historical research

`run_full_pipeline.py`, CPPI scripts, sell-side-brake reports and historical
figures belong to the legacy research track. They are not the admission gate or
performance record for the current strategy. See
[`LEGACY_RESEARCH_NOTICE.md`](LEGACY_RESEARCH_NOTICE.md) before using them.

## Release safety

```bash
python3 scripts/check_public_release.py
```

This verifies that the proposed public source does not include local tokens,
raw/processed caches, generated portfolios, the independently maintained site
repository or oversized files.
