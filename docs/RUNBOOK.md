# Runbook

> The cycle-rotation commands below document the legacy research pipeline and
> are not the current strategy's verified performance record. For the current
> forward workflow, start with the repository README. See
> `docs/LEGACY_RESEARCH_NOTICE.md` before interpreting any backtest output.

## 1. Before running

```bash
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill `TUSHARE_TOKEN` in `.env` if you need to fetch new data.

## 2. Smoke test

```bash
pytest -q
```

## 3. Final decision refresh

Use this when the existing processed data is already present:

```bash
python scripts/run_final_assembly.py
python scripts/run_complement_engine.py
python scripts/run_complement_valuation.py
python scripts/run_current_cycle_decision.py
```

## 4. Important outputs

```text
data/processed/selection/final_candidates.csv
data/processed/selection/today_cycle_decision.csv
data/processed/selection/today_cycle_decision.txt
```

## 5. Cycle rotation portfolio sheet

The portfolio sheet implements the allocation sequence below on the full
cached A-share market data:

1. A depressed 252-day price position plus 5/60-day volume expansion creates a
   `BOTTOM_BASE` signal and permits a 15% total cycle base allocation.
2. A 60-day trend, 20-day breakout and stronger volume confirmation create a
   `TREND_ADD` signal. Each confirmed name adds 10 percentage points of total
   cycle exposure, capped at 45%.
3. The balance is assigned only to manually approved moat names that also pass
   dividend-yield and PB checks. If none are approved, it remains cash instead
   of treating yield as proof of a moat.

```bash
# Uses the existing close/volume matrix.
python scripts/run_rotation_portfolio.py

# Extends full-market close/volume and daily-basic through the latest completed
# SSE trading day; token must be supplied through .env or shell.
python scripts/refresh_rotation_market_data.py
python scripts/run_rotation_portfolio.py
```

Review and populate `config/defensive_watchlist.csv` before enabling defensive
allocations. The outputs are:

```text
data/processed/portfolio/cycle_signals.csv
data/processed/portfolio/defensive_signals.csv
data/processed/portfolio/target_portfolio.csv
data/processed/portfolio/portfolio_summary.csv
```

## 6. Common issues

- `Missing TUSHARE_TOKEN`: create `.env` and fill your TuShare token.
- `Missing xxx.csv/parquet`: run the upstream script that creates that file.
- API quota error: reduce `max_stocks` in `config/config.yaml` or use cached data.

## 7. SW industry cycle and value screen

```bash
python3 scripts/refresh_rotation_market_data.py --as-of YYYYMMDD
python3 scripts/run_sw_industry_value_screen.py --max-financials 40
```

Use `--refresh` only when SW membership or cached statements must be downloaded
again. Outputs are written to `outputs/sw-industry-value-screen/`. A
`VALUATION_WATCH` row is not a buy signal: the cash-flow valuation passed but
the industry has not yet reached a confirmed bottoming/recovery state.
