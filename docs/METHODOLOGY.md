# Methodology

This note records the methods implemented in the current barbell pipeline. It is intentionally narrower than a research manifesto: if a rule is not in the code or configuration, it is not described as an implemented feature.

## Point-in-time data discipline

Annual statement rows are normalised by `end_date` and, when available, the latest `ann_date` for that period. The valuation path uses only information available to the requested as-of date. Later filings must not be used to rewrite an earlier target or NAV observation. Missing or failed requests remain unavailable; they are not interpreted as zero profit, zero risk or a clean scan.

## Candidate screening

The anchor screen combines:

- valuation multiples, dividend yield and owner-earnings yield;
- positive owner-earnings and FCF history;
- normalised ROE, revenue trend, gross-margin stability and FCF conversion;
- leverage/net-cash checks and owner-earnings variability;
- listing history, market-cap and sub-industry position;
- industry, economic-factor and single-name caps;
- data-completeness and moat-proxy gates.

The screen creates a conservative research baseline. It does not claim that an industry leader automatically has an economic moat.

## Policy and future demand

`selection/policy_alignment.py` requires a national-plan source and a government URL containing `gov.cn` for policy eligibility. Policy is used to focus research on durable demand directions and possible profit pools. It is not a direct stock-return model.

Future-demand scores use demand certainty, bottleneck strength, value capture, exposure confidence, competition risk and substitution risk. A valuation gate is a constraint rather than a thesis score. The report states that a high future-demand score is research priority, not a buy signal, because demand certainty is not profit certainty.

Future milestone records remain `UNVERIFIED` unless a dated, source-backed review changes them. Scripts do not silently promote `config/future-milestones.csv`.

## Moat framework and evidence

A moat card is a falsifiable business hypothesis: what advantage exists, why it is difficult to replicate, which operating outcomes should follow, what to monitor, what would contradict the thesis and when to review it.

Trusted evidence types are company filings, government primary material and first-hand industry material. The evidence ledger is append-only and requires a source URL and evidence date. The monitor maps evidence direction to:

- `DRAFT` when the thesis is not yet supported by a qualifying source;
- `INTACT` when qualifying support exists;
- `WATCH` when caution evidence is present;
- `WEAKENED` when contradiction evidence is present;
- `REVIEW_DUE` when the scheduled review date has passed.

Financial results can validate the economic output of a moat, but financial metrics alone cannot promote a draft card. `config/moat-human-review.csv` records a human boolean for review status; that boolean is not a model allocation gate.

The radar separately scans announcement and financial anomalies. Its alerts are `PENDING_REVIEW`, and its health file distinguishes `OK`, `PARTIAL`, `UNAVAILABLE` and `OFFLINE` coverage. No alert is an automatic order instruction.

## Owner-earnings DCF

For each annual period, owner earnings are calculated as:

```text
owner earnings = net income + depreciation/amortisation - maintenance capex
maintenance capex = min(capex, 1.10 × depreciation) when depreciation is positive
```

The normalised owner-earnings input is the median of the latest three annual observations. Net cash is cash less the configured debt fields. The DCF projects five years of capped growth and a terminal value:

```text
PV = Σ earnings_t / (1 + r)^t
terminal value = earnings_5 × (1 + g_terminal) / (r - g_terminal)
equity value = PV + terminal value / (1 + r)^5 + net cash
per-share value = equity value / total shares
```

The default growth is 3%, clipped to -2%–6%. Terminal growth is 2.5%. The base required return is 10%, and the five sensitivity rates move by one percentage point: 8%, 9%, 10%, 11% and 12%. The rate is never allowed to fall below terminal growth plus two percentage points.

The base value is the mechanical DCF gate used by the strategy. The other four values are sensitivity references; they do not alter the underlying operating inputs.

## Position states and cash

Future-demand candidates use the following ladder:

| State | Target step | Gate |
| --- | ---: | --- |
| `RESEARCH_ONLY` | no allocation | one or more policy, thesis, value, cash-earnings, timing or evidence gates fail |
| `OPTION_SEED` | 2.5% | seed evidence and timing gates pass |
| `CONFIRMED_BUILD` | 5% | at least two milestone classes are verified |
| `PROMOTED_CORE` | 7.5% | all three milestone classes, no unresolved invalidation and trend confirmation |

The configured future cap is 25%, the single-theme cap is 15% and the cash floor is 10%. Anchors have a 65% target budget, 15% single-name cap and sticky behavior. Existing anchors are reduced in documented steps rather than automatically replaced because a daily score moved slightly. Cash remains when qualified exposure is unavailable or capped.

## T+1 execution boundary

The published close-time target is effective on the next trading day. The model’s open-price proxy is only a reproducible reference; it is not a promise that an account can fill at that price. The nested website has a browser-local actual-fill ledger for price, quantity and fee. Actual fills change the personal view and slippage calculation, not the public model NAV.

## Dividend accounting

The forward ledger uses raw closing prices plus a tax-adjusted `cash_div` proxy and `stk_div` split ratio. Ex-rights date records entitlement, pay date creates pending cash, and the next session reinvests pending cash by target weight. Adjusted prices are not used alongside separate distributions.

## Benchmark methodology

The website uses `000300.SH` (CSI 300) raw close as a price-index proxy. It normalises the first shared record to 1.0 and does not add index dividends. Missing benchmark dates are reported as `PARTIAL` or `UNAVAILABLE`; the portfolio return is never substituted for a missing benchmark observation.

## Reproducibility and limitations

Run the scripts in the order documented in the root README and keep the as-of date at the latest completed trading day. Use `--offline` only when cache-only behavior is intended. Tushare permissions and network availability can change the coverage status. The forward record has a limited sample and is not a complete transaction-cost-aware rolling out-of-sample study. Older cycle/CPPI scripts are historical research and should not be used as current barbell performance evidence.
