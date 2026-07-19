# Methodology

This note records the methods implemented in the current barbell pipeline. The five-scenario DCF establishes a **margin-of-safety** boundary, while moat evidence remains a separate falsifiable research hypothesis. It is intentionally narrower than a research manifesto: if a rule is not in the code or configuration, it is not described as an implemented feature.

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

A moat card is a falsifiable business hypothesis: what advantage exists, why it is difficult to replicate, which operating outcomes should follow, what to monitor, what would contradict the thesis and when to review it. Evidence may involve brands, technology and standards, cost leadership, supply-chain control, scarce resources, licences, channels, switching costs or ecosystem position.

Trusted evidence types are company filings, government primary material and first-hand industry material. The evidence ledger is append-only and requires a source URL and evidence date. The monitor maps evidence direction to:

- `DRAFT` when the thesis is not yet supported by a qualifying source;
- `INTACT` when qualifying support exists;
- `WATCH` when caution evidence is present;
- `WEAKENED` when contradiction evidence is present;
- `REVIEW_DUE` when the scheduled review date has passed.

Financial results can validate the economic output of a moat, but financial metrics alone cannot promote a draft card. `config/moat-human-review.csv` records a human boolean for review status; that boolean is not a model allocation gate. Every mechanism must include value-capture evidence and disconfirming signals; no ranked company is confirmed solely because a machine proxy passed.

The radar separately scans announcement and financial anomalies. Its alerts are `PENDING_REVIEW`, and its health file distinguishes `OK`, `PARTIAL`, `UNAVAILABLE` and `OFFLINE` coverage. No alert is an automatic order instruction.

## Owner-earnings DCF

Implementation: [`valuation/owner_earnings.py`](../valuation/owner_earnings.py), with point-in-time callers in [`scripts/run_barbell_strategy.py`](../scripts/run_barbell_strategy.py) and [`scripts/run_future_demand_screen.py`](../scripts/run_future_demand_screen.py).

### Annual owner earnings

The implementation keeps year-end (`end_date` ending in `1231`) statement rows and, when `ann_date` is present, keeps the latest announced row for each period. It retains the latest five annual periods available to the calculation. For each period, the fields are:

$$
\begin{aligned}
NI_t &= \text{n\_income\_attr\_p, falling back to n\_income}\\
D_t &= \sum(\text{depr\_fa\_coga\_dpba},\ \text{amort\_intang\_assets},\ \text{lt\_amort\_deferred\_exp})\\
MCapEx_t &= \min(CapEx_t,\ 1.10\times D_t)\quad\text{when }CapEx_t\text{ is present and }D_t>0\\
OE_t &= NI_t + D_t - MCapEx_t
\end{aligned}
$$

Here `CapEx_t` is `c_pay_acq_const_fiolta`. If the capex field is unavailable, the period's owner earnings are unavailable; if depreciation is not positive, the code uses reported capex directly as the maintenance-capex proxy. Operating cash flow is **not** substituted into the owner-earnings formula. It is used separately to calculate `FCF_t = OCF_t - CapEx_t` and to test cash-earnings quality. There is no separate working-capital-change term: any working-capital effect must already be reflected in the source statements.

The normalized starting value is the median of the latest three available owner-earnings observations:

$$
OE_0 = \operatorname{median}(OE_{T-2}, OE_{T-1}, OE_T)
$$

The DCF returns unavailable when normalized owner earnings or shares are non-positive. Callers pass Tushare `total_share` multiplied by 10,000 to convert the reported unit into shares. Net cash is:

$$
NetCash = money\_cap - (st\_borr + lt\_borr + bond\_payable + non\_cur\_liab\_due\_1y)
$$

Missing cash is treated as zero; missing individual debt fields are omitted from the debt sum.

### Forecast and present value

Forecast owner earnings use a constant, bounded growth rate:

$$
OE_t = OE_0(1+g)^t,\qquad t=1,\ldots,N
$$

The default `g` is 3%, clipped to the implemented range −2% to 6%, and `N` is five years. Explicit forecast value is:

$$
PV_{forecast}=\sum_{t=1}^{N}\frac{OE_t}{(1+r)^t}
$$

where `r` is the scenario discount rate and `N=5` in the default pipeline.

### Terminal value, equity value and per-share value

The terminal growth rate is `g∞ = 2.5%`. The code applies a required-return floor `r = max(input r, g∞ + 2%)` before calculating:

$$
TV_N=\frac{OE_N(1+g_\infty)}{r-g_\infty},\qquad
PV_{terminal}=\frac{TV_N}{(1+r)^N}
$$

Then:

$$
EquityValue=PV_{forecast}+PV_{terminal}+NetCash
$$

$$
IntrinsicValuePerShare=\frac{EquityValue}{SharesOutstanding}
$$

The value is floored at zero after division. This is an operating-company owner-earnings model; it is not a residual-income model for financial companies.

### Margin of safety convention

The screening callers align the market price to the same point-in-time row and calculate the displayed margin as:

$$
Margin_{model}=\frac{IntrinsicValuePerShare}{MarketClose}-1
$$

This is the model's upside-versus-close convention, not the textbook `(intrinsic value − price) / intrinsic value` convention. A positive number means the scenario value is above the aligned market close; missing price or value produces an unavailable margin.

### Five discount-rate scenarios

The five displayed cases hold normalized owner earnings, net cash, shares, growth, terminal growth and forecast length constant. Only the discount rate changes:

| Scenario | Discount rate |
| --- | ---: |
| `VERY_OPTIMISTIC` | 8% |
| `OPTIMISTIC` | 9% |
| `BASE` | 10% |
| `CAUTIOUS` | 11% |
| `VERY_PESSIMISTIC` | 12% |

The base value is the repeatable mechanical DCF gate. The other four values expose sensitivity for review; they do not silently rewrite the operating forecast to manufacture a wider range. Tests in [`tests/test_owner_earnings.py`](../tests/test_owner_earnings.py) verify the five rates, ordering and BASE-field compatibility.

### Interpretation and limitations

- Owner earnings are normalized estimates, not reported accounting line items.
- Growth is bounded but still uncertain; the terminal value can represent a large share of total value.
- Net cash and share count depend on the quality and timing of source data.
- DCF does not prove that a moat exists, and a low price can still be a value trap.
- The 10% base case is a repeatable threshold for the strategy, not a guaranteed fair value.

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
