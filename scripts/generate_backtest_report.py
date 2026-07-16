# Allow running this file directly from the project root, e.g.
# python scripts/generate_backtest_report.py
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import os
import warnings

import pandas as pd
import numpy as np
from dotenv import load_dotenv

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


NAV_PATH = Path("data/processed/selection/cycle_base_sequence_cppi_nav.csv")
TRADES_PATH = Path("data/processed/selection/cycle_base_sequence_cppi_trades.csv")
SUMMARY_PATH = Path("data/processed/selection/cycle_base_sequence_cppi_summary.csv")
DECISION_TXT_PATH = Path("data/processed/selection/today_cycle_decision.txt")

STOCK_RETURNS_PATH = Path("data/processed/selection/stock_return_matrix.csv")
BENCHMARK_DIR = Path("data/processed/benchmarks")
CSI300_CACHE_PATH = BENCHMARK_DIR / "csi300_returns.csv"

OUT_DIR = Path("outputs/backtest_report")

TRADING_DAYS = 252
RISK_FREE_RATE = 0.015
RISK_FREE_DAILY = (1 + RISK_FREE_RATE) ** (1 / TRADING_DAYS) - 1

BENCHMARK_STOCKS = {
    "Yangtze Power 600900.SH": "600900.SH",
    "Kweichow Moutai 600519.SH": "600519.SH",
}


def require_file(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(
            f"Missing required file: {path}. "
            "Run `python scripts/run_full_pipeline.py` first."
        )


def pct(x: float) -> str:
    if pd.isna(x):
        return "N/A"
    return f"{x * 100:.2f}%"


def num(x: float) -> str:
    if pd.isna(x):
        return "N/A"
    return f"{x:.3f}"


def load_nav() -> pd.DataFrame:
    require_file(NAV_PATH)
    nav = pd.read_csv(NAV_PATH)
    nav["trade_date"] = pd.to_datetime(nav["trade_date"])
    nav = nav.sort_values("trade_date").reset_index(drop=True)
    if "nav" not in nav.columns:
        raise ValueError(f"{NAV_PATH} must contain a 'nav' column.")
    nav["drawdown"] = nav["nav"] / nav["nav"].cummax() - 1
    nav["daily_return"] = nav["nav"].pct_change().fillna(0)
    return nav


def load_summary() -> pd.DataFrame:
    require_file(SUMMARY_PATH)
    return pd.read_csv(SUMMARY_PATH)


def load_trades() -> pd.DataFrame:
    require_file(TRADES_PATH)
    trades = pd.read_csv(TRADES_PATH)
    if "trade_date" in trades.columns:
        trades["trade_date"] = pd.to_datetime(trades["trade_date"])
    return trades


def load_stock_returns() -> pd.DataFrame | None:
    if not STOCK_RETURNS_PATH.exists():
        warnings.warn(
            f"Missing {STOCK_RETURNS_PATH}; stock benchmarks will be skipped."
        )
        return None

    df = pd.read_csv(STOCK_RETURNS_PATH)
    first_col = df.columns[0]
    if first_col != "trade_date":
        df = df.rename(columns={first_col: "trade_date"})
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    return df.sort_values("trade_date").reset_index(drop=True)


def fetch_csi300_from_tushare(start_date, end_date) -> pd.DataFrame | None:
    """Fetch CSI 300 index returns from TuShare and cache them locally.

    This is optional. If no token is configured or the request fails, the report
    still generates the remaining benchmarks.
    """
    load_dotenv()
    token = os.getenv("TUSHARE_TOKEN") or os.getenv("TS_TOKEN")
    if not token:
        warnings.warn(
            "No TUSHARE_TOKEN found. CSI 300 benchmark will be skipped unless "
            f"{CSI300_CACHE_PATH} already exists."
        )
        return None

    try:
        import tushare as ts
    except Exception as exc:
        warnings.warn(f"Unable to import tushare; CSI 300 skipped. Error: {exc}")
        return None

    try:
        ts.set_token(token)
        pro = ts.pro_api()
        raw = pro.index_daily(
            ts_code="000300.SH",
            start_date=pd.Timestamp(start_date).strftime("%Y%m%d"),
            end_date=pd.Timestamp(end_date).strftime("%Y%m%d"),
        )
    except Exception as exc:
        warnings.warn(f"TuShare index_daily failed; CSI 300 skipped. Error: {exc}")
        return None

    if raw is None or raw.empty:
        warnings.warn("TuShare returned empty CSI 300 data.")
        return None

    raw = raw.copy()
    raw["trade_date"] = pd.to_datetime(raw["trade_date"])
    raw = raw.sort_values("trade_date")
    if "pct_chg" in raw.columns:
        raw["return"] = raw["pct_chg"].astype(float) / 100
    else:
        raw["close"] = raw["close"].astype(float)
        raw["return"] = raw["close"].pct_change().fillna(0)

    out = raw[["trade_date", "return"]].dropna()
    BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(CSI300_CACHE_PATH, index=False, encoding="utf-8-sig")
    return out


def load_csi300_returns(start_date, end_date) -> pd.DataFrame | None:
    if CSI300_CACHE_PATH.exists():
        csi = pd.read_csv(CSI300_CACHE_PATH)
        csi["trade_date"] = pd.to_datetime(csi["trade_date"])
        if "return" not in csi.columns:
            raise ValueError(f"{CSI300_CACHE_PATH} must contain a 'return' column.")
        return csi[["trade_date", "return"]].sort_values("trade_date")

    return fetch_csi300_from_tushare(start_date, end_date)


def nav_from_returns(dates: pd.Series, returns: pd.Series) -> pd.Series:
    r = pd.Series(returns).fillna(0).astype(float).reset_index(drop=True)
    if len(r) > 0:
        r.iloc[0] = 0.0
    return (1 + r).cumprod()


def build_benchmark_nav(nav: pd.DataFrame) -> pd.DataFrame:
    base = nav[["trade_date", "nav"]].rename(columns={"nav": "Strategy"}).copy()
    start_date = base["trade_date"].min()
    end_date = base["trade_date"].max()

    # Risk-free benchmark.
    base["Risk-Free 1.5%"] = nav_from_returns(
        base["trade_date"],
        pd.Series(RISK_FREE_DAILY, index=base.index),
    )

    # Stock benchmarks from existing return matrix.
    stock_returns = load_stock_returns()
    if stock_returns is not None:
        stock_returns = stock_returns[
            (stock_returns["trade_date"] >= start_date)
            & (stock_returns["trade_date"] <= end_date)
        ]
        for label, code in BENCHMARK_STOCKS.items():
            if code not in stock_returns.columns:
                warnings.warn(f"{code} not found in {STOCK_RETURNS_PATH}; skipped.")
                continue
            tmp = stock_returns[["trade_date", code]].rename(columns={code: "return"})
            base = base.merge(tmp, on="trade_date", how="left")
            base[label] = nav_from_returns(base["trade_date"], base["return"])
            base = base.drop(columns=["return"])

    # CSI 300 benchmark.
    csi = load_csi300_returns(start_date, end_date)
    if csi is not None and not csi.empty:
        csi = csi[
            (csi["trade_date"] >= start_date)
            & (csi["trade_date"] <= end_date)
        ]
        base = base.merge(csi[["trade_date", "return"]], on="trade_date", how="left")
        base["CSI 300 000300.SH"] = nav_from_returns(base["trade_date"], base["return"])
        base = base.drop(columns=["return"])
    else:
        warnings.warn("CSI 300 benchmark not available.")

    # Normalize all benchmark lines to 1.0 at first available value.
    for col in base.columns:
        if col == "trade_date":
            continue
        first_valid = base[col].dropna()
        if not first_valid.empty and first_valid.iloc[0] != 0:
            base[col] = base[col] / first_valid.iloc[0]

    base.to_csv(OUT_DIR / "benchmark_nav.csv", index=False, encoding="utf-8-sig")
    return base


def compute_metrics_from_nav(label: str, nav_series: pd.Series) -> dict:
    series = pd.Series(nav_series).dropna().astype(float)
    if len(series) < 2:
        return {
            "Portfolio": label,
            "Annual Return": np.nan,
            "Annual Volatility": np.nan,
            "Sharpe": np.nan,
            "Max Drawdown": np.nan,
            "Final NAV": np.nan,
        }

    ret = series.pct_change().dropna()
    years = len(ret) / TRADING_DAYS
    annual_return = series.iloc[-1] ** (1 / years) - 1 if years > 0 else np.nan
    annual_vol = ret.std() * np.sqrt(TRADING_DAYS)
    excess = ret - RISK_FREE_DAILY
    sharpe = excess.mean() / ret.std() * np.sqrt(TRADING_DAYS) if ret.std() > 0 else np.nan
    dd = series / series.cummax() - 1

    return {
        "Portfolio": label,
        "Annual Return": annual_return,
        "Annual Volatility": annual_vol,
        "Sharpe": sharpe,
        "Max Drawdown": dd.min(),
        "Final NAV": series.iloc[-1],
    }


def make_benchmark_metrics(benchmark_nav: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for col in benchmark_nav.columns:
        if col == "trade_date":
            continue
        rows.append(compute_metrics_from_nav(col, benchmark_nav[col]))
    df = pd.DataFrame(rows)
    df.to_csv(OUT_DIR / "benchmark_metrics_raw.csv", index=False, encoding="utf-8-sig")

    formatted = df.copy()
    for col in ["Annual Return", "Annual Volatility", "Max Drawdown"]:
        formatted[col] = formatted[col].map(pct)
    for col in ["Sharpe", "Final NAV"]:
        formatted[col] = formatted[col].map(num)
    formatted.to_csv(OUT_DIR / "benchmark_metrics.csv", index=False, encoding="utf-8-sig")
    return formatted


def plot_nav(nav: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(11, 5.8))
    ax.plot(nav["trade_date"], nav["nav"], linewidth=2)
    ax.set_title("Cycle rotation CPPI strategy NAV")
    ax.set_xlabel("Date")
    ax.set_ylabel("NAV")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "nav_curve.png", dpi=160)
    plt.close(fig)


def plot_benchmark_nav(benchmark_nav: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(11.5, 6.2))
    for col in benchmark_nav.columns:
        if col == "trade_date":
            continue
        ax.plot(benchmark_nav["trade_date"], benchmark_nav[col], linewidth=1.8, label=col)
    ax.set_title("Strategy vs benchmarks")
    ax.set_xlabel("Date")
    ax.set_ylabel("Normalized NAV")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUT_DIR / "benchmark_comparison.png", dpi=160)
    plt.close(fig)


def plot_drawdown(nav: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(11, 5.8))
    ax.fill_between(nav["trade_date"], nav["drawdown"] * 100, 0, alpha=0.35)
    ax.plot(nav["trade_date"], nav["drawdown"] * 100, linewidth=1.5)
    ax.set_title("Strategy drawdown")
    ax.set_xlabel("Date")
    ax.set_ylabel("Drawdown (%)")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "drawdown_curve.png", dpi=160)
    plt.close(fig)


def plot_weights(nav: pd.DataFrame) -> None:
    cols = [
        c for c in [
            "cycle_weight",
            "anchor_weight",
            "risk_free_weight",
        ]
        if c in nav.columns
    ]
    if not cols:
        return

    fig, ax = plt.subplots(figsize=(11, 5.8))
    for col in cols:
        ax.plot(nav["trade_date"], nav[col] * 100, linewidth=1.6, label=col)
    ax.set_title("Portfolio exposure over time")
    ax.set_xlabel("Date")
    ax.set_ylabel("Weight (%)")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUT_DIR / "exposure_weights.png", dpi=160)
    plt.close(fig)


def plot_trade_actions(trades: pd.DataFrame) -> None:
    if "action" not in trades.columns or trades.empty:
        return

    counts = trades["action"].value_counts().sort_values(ascending=True)
    fig, ax = plt.subplots(figsize=(10, 5.8))
    ax.barh(counts.index.astype(str), counts.values)
    ax.set_title("Trade action counts")
    ax.set_xlabel("Count")
    ax.set_ylabel("Action")
    ax.grid(True, axis="x", alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "trade_action_counts.png", dpi=160)
    plt.close(fig)


def build_event_attribution(nav: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    """Create a compact event attribution table for major trading events.

    This is a reporting layer only. It reads generated NAV/trade files and does
    not change any backtest parameter or trading rule.
    """
    if trades.empty or "action" not in trades.columns or "trade_date" not in trades.columns:
        return pd.DataFrame()

    important_actions = {
        "STEP_ADD",
        "SELL_SIDE_BRAKE",
        "DROP_EXPANSION_TO_BASE",
        "SEQUENCE_CONFIRMED_OPEN_STEP_RISK",
        "TIME_SURVIVED_ACCUMULATION_CONFIRMED",
    }

    x = trades[trades["action"].isin(important_actions)].copy()
    if x.empty:
        return pd.DataFrame()

    nav_lookup = nav[["trade_date", "nav", "drawdown"]].copy()
    x = x.merge(nav_lookup, on="trade_date", how="left")

    keep_cols = [
        "trade_date",
        "action",
        "theme",
        "theme_regime",
        "nav",
        "drawdown",
        "old_cycle_weight",
        "new_cycle_weight",
        "cycle_weight",
        "target_cycle_weight",
        "brake_type",
        "brake_reason",
        "current_price",
        "last_add_price",
        "drawdown_from_last_add",
    ]
    keep_cols = [c for c in keep_cols if c in x.columns]

    result = x[keep_cols].sort_values("trade_date").reset_index(drop=True)
    result.to_csv(OUT_DIR / "event_attribution.csv", index=False, encoding="utf-8-sig")
    return result


def plot_nav_attribution_events(nav: pd.DataFrame, event_attr: pd.DataFrame) -> None:
    nav = nav.copy()

    if "trade_date" not in nav.columns:
        nav = nav.reset_index().rename(columns={"index": "trade_date"})

    nav["trade_date"] = pd.to_datetime(nav["trade_date"])

    if "nav" not in nav.columns:
        print("[WARN] plot_nav_attribution_events skipped: nav has no 'nav' column")
        print("[WARN] nav columns:", list(nav.columns))
        return

    fig, ax = plt.subplots(figsize=(12.5, 6.4))
    ax.plot(nav["trade_date"], nav["nav"], linewidth=2.4, label="Strategy NAV")

    if event_attr is not None and not event_attr.empty:
        event_attr = event_attr.copy()
        event_attr["trade_date"] = pd.to_datetime(event_attr["trade_date"])

        if "nav" not in event_attr.columns:
            event_attr = event_attr.merge(
                nav[["trade_date", "nav"]],
                on="trade_date",
                how="left",
            )

        if "nav" not in event_attr.columns:
            print("[WARN] event_attr still has no nav column, skip event markers")
        else:
            marker_spec = {
                "STEP_ADD": {"marker": "^", "label": "Step add"},
                "SELL_SIDE_BRAKE": {"marker": "v", "label": "Sell-side brake"},
                "DROP_EXPANSION_TO_BASE": {"marker": "x", "label": "Drop to base"},
            }

            for action, spec in marker_spec.items():
                subset = event_attr[event_attr["action"] == action].copy()
                if subset.empty:
                    continue

                subset = subset.dropna(subset=["nav"])

                if subset.empty:
                    continue

                ax.scatter(
                    subset["trade_date"],
                    subset["nav"],
                    marker=spec["marker"],
                    s=70,
                    label=spec["label"],
                    alpha=0.85,
                )

            key_events = [
                ("2020-07-02", "COAL expansion"),
                ("2021-09-03", "OIL expansion"),
                ("2025-09-05", "LITHIUM expansion"),
            ]

            for date_str, label in key_events:
                dt = pd.to_datetime(date_str)
                row = event_attr[
                    (event_attr["trade_date"] == dt)
                    & (event_attr["action"] == "STEP_ADD")
                ]
                if row.empty or pd.isna(row.iloc[0].get("nav")):
                    continue

                row = row.iloc[0]

                ax.annotate(
                    label,
                    xy=(row["trade_date"], row["nav"]),
                    xytext=(12, 18),
                    textcoords="offset points",
                    fontsize=9,
                    ha="left",
                    arrowprops={"arrowstyle": "->", "linewidth": 0.8, "alpha": 0.7},
                )

    ax.set_title("Strategy NAV with key cycle events")
    ax.set_xlabel("Date")
    ax.set_ylabel("NAV")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left")
    fig.tight_layout()
    fig.savefig(OUT_DIR / "nav_attribution_events.png", dpi=170)
    plt.close(fig)

def make_event_summary(event_attr: pd.DataFrame) -> pd.DataFrame:
    if event_attr is None or event_attr.empty:
        out = pd.DataFrame(columns=["Action", "Count", "Themes"])
        out.to_csv(OUT_DIR / "event_summary.csv", index=False, encoding="utf-8-sig")
        return out

    rows = []
    for action, group in event_attr.groupby("action"):
        themes = (
            group["theme"]
            .dropna()
            .astype(str)
            .str.upper()
            .value_counts()
            .to_dict()
            if "theme" in group.columns
            else {}
        )
        theme_text = ", ".join([f"{k}: {v}" for k, v in themes.items()])
        rows.append(
            {
                "Action": action,
                "Count": len(group),
                "Themes": theme_text,
            }
        )
    out = pd.DataFrame(rows).sort_values("Count", ascending=False)
    out.to_csv(OUT_DIR / "event_summary.csv", index=False, encoding="utf-8-sig")
    return out



def make_metrics_table(summary: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    row = summary.iloc[0].to_dict()

    metrics = [
        ("Annual return", pct(float(row.get("annual_return", np.nan)))),
        ("Annual volatility", pct(float(row.get("annual_vol", np.nan)))),
        ("Sharpe ratio", num(float(row.get("sharpe", np.nan)))),
        ("Sortino ratio", num(float(row.get("sortino", np.nan)))),
        ("Max drawdown", pct(float(row.get("max_drawdown", np.nan)))),
        ("Calmar ratio", num(float(row.get("calmar", np.nan)))),
        ("Final NAV", num(float(row.get("final_nav", np.nan)))),
        ("Average cycle weight", pct(float(row.get("avg_cycle_weight", np.nan)))),
        ("Max cycle weight", pct(float(row.get("max_cycle_weight", np.nan)))),
        ("Base entries", str(int(row.get("num_base_entries", 0)))),
        ("Sequence confirmations", str(int(row.get("num_sequence_confirms", 0)))),
        ("Step adds", str(int(row.get("num_step_adds", 0)))),
        ("Expansion drops", str(int(row.get("num_drop_expansion", 0)))),
        ("Sell-side brakes", str(int(row.get("num_sell_side_brakes", 0)))),
        ("Brake days", str(int(row.get("brake_days", 0)))),
        ("Observations", str(int(row.get("n_obs", 0)))),
    ]

    action_counts = trades["action"].value_counts().to_dict() if "action" in trades.columns else {}
    for action in ["STEP_ADD", "DROP_EXPANSION_TO_BASE", "SELL_SIDE_BRAKE"]:
        if action in action_counts:
            metrics.append((f"Trade count: {action}", str(int(action_counts[action]))))

    df = pd.DataFrame(metrics, columns=["Metric", "Value"])
    df.to_csv(OUT_DIR / "backtest_metrics.csv", index=False, encoding="utf-8-sig")
    return df


def make_report(
    nav: pd.DataFrame,
    trades: pd.DataFrame,
    summary: pd.DataFrame,
    metrics_df: pd.DataFrame,
    benchmark_metrics_df: pd.DataFrame,
    event_summary_df: pd.DataFrame,
) -> None:
    row = summary.iloc[0].to_dict()

    action_counts = trades["action"].value_counts() if "action" in trades.columns else pd.Series(dtype=int)
    theme_counts = trades["theme"].value_counts() if "theme" in trades.columns else pd.Series(dtype=int)

    latest_date = nav["trade_date"].iloc[-1].date()
    start_date = nav["trade_date"].iloc[0].date()

    decision_text = ""
    if DECISION_TXT_PATH.exists():
        decision_text = DECISION_TXT_PATH.read_text(encoding="utf-8", errors="ignore").strip()

    metrics_markdown = metrics_df.to_markdown(index=False)
    benchmark_markdown = benchmark_metrics_df.to_markdown(index=False)
    event_summary_markdown = (
        event_summary_df.to_markdown(index=False)
        if event_summary_df is not None and not event_summary_df.empty
        else "No major cycle events found."
    )

    report = f"""# Backtest Report

This report is generated from the local strategy outputs. It does not change any
strategy parameter or trading rule.

## Summary

- Backtest window: `{start_date}` to `{latest_date}`
- Final NAV: `{num(float(row.get("final_nav", np.nan)))}`
- Annual return: `{pct(float(row.get("annual_return", np.nan)))}`
- Sharpe ratio: `{num(float(row.get("sharpe", np.nan)))}`
- Sortino ratio: `{num(float(row.get("sortino", np.nan)))}`
- Maximum drawdown: `{pct(float(row.get("max_drawdown", np.nan)))}`
- Average cycle weight: `{pct(float(row.get("avg_cycle_weight", np.nan)))}`
- Maximum cycle weight: `{pct(float(row.get("max_cycle_weight", np.nan)))}`

## Benchmark comparison

Benchmarks are normalized to 1.0 at the beginning of the backtest window.

Included when data is available:

- Risk-Free 1.5%
- Yangtze Power `600900.SH`
- Kweichow Moutai `600519.SH`
- CSI 300 `000300.SH`

![Benchmark comparison](benchmark_comparison.png)

### Benchmark metrics

{benchmark_markdown}

## Cycle event attribution

The chart below overlays major cycle actions on the strategy NAV. It is meant to
show whether large NAV moves coincide with the strategy's own expansion,
de-risking, and brake signals.

![NAV attribution events](nav_attribution_events.png)

### Event summary

{event_summary_markdown}

## Charts

### NAV curve

![NAV curve](nav_curve.png)

### Drawdown curve

Drawdown is measured relative to the strategy's own historical high-water mark:

```text
drawdown = current NAV / historical max NAV - 1
```

A strategy can have a rising long-term NAV while its drawdown stays below zero
whenever it has not yet recovered to a previous peak.

![Drawdown curve](drawdown_curve.png)

### Exposure weights

![Exposure weights](exposure_weights.png)

### Trade action counts

![Trade action counts](trade_action_counts.png)

## Strategy metrics

{metrics_markdown}

## Trade action counts

```text
{action_counts.to_string() if not action_counts.empty else "No trade actions found."}
```

## Theme counts

```text
{theme_counts.to_string() if not theme_counts.empty else "No theme counts found."}
```

## Latest decision snapshot

```text
{decision_text if decision_text else "Run `python scripts/run_current_cycle_decision.py` to generate today's decision report."}
```

## Notes

The report is produced by:

```bash
python scripts/generate_backtest_report.py
```

It reads:

- `data/processed/selection/cycle_base_sequence_cppi_nav.csv`
- `data/processed/selection/cycle_base_sequence_cppi_trades.csv`
- `data/processed/selection/cycle_base_sequence_cppi_summary.csv`
- `data/processed/selection/stock_return_matrix.csv`

For a full refresh, run:

```bash
python scripts/run_full_pipeline.py
python scripts/generate_backtest_report.py
```
"""
    (OUT_DIR / "BACKTEST_REPORT.md").write_text(report, encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    nav = load_nav()
    trades = load_trades()
    summary = load_summary()

    plot_nav(nav)
    plot_drawdown(nav)
    plot_weights(nav)
    plot_trade_actions(trades)

    benchmark_nav = build_benchmark_nav(nav)
    benchmark_metrics_df = make_benchmark_metrics(benchmark_nav)
    plot_benchmark_nav(benchmark_nav)

    event_attr = build_event_attribution(nav, trades)
    plot_nav_attribution_events(nav, event_attr)
    event_summary_df = make_event_summary(event_attr)

    metrics_df = make_metrics_table(summary, trades)
    make_report(nav, trades, summary, metrics_df, benchmark_metrics_df, event_summary_df)

    print(f"saved: {OUT_DIR / 'nav_curve.png'}")
    print(f"saved: {OUT_DIR / 'benchmark_comparison.png'}")
    print(f"saved: {OUT_DIR / 'nav_attribution_events.png'}")
    print(f"saved: {OUT_DIR / 'event_attribution.csv'}")
    print(f"saved: {OUT_DIR / 'event_summary.csv'}")
    print(f"saved: {OUT_DIR / 'drawdown_curve.png'}")
    print(f"saved: {OUT_DIR / 'exposure_weights.png'}")
    print(f"saved: {OUT_DIR / 'trade_action_counts.png'}")
    print(f"saved: {OUT_DIR / 'backtest_metrics.csv'}")
    print(f"saved: {OUT_DIR / 'benchmark_nav.csv'}")
    print(f"saved: {OUT_DIR / 'benchmark_metrics.csv'}")
    print(f"saved: {OUT_DIR / 'BACKTEST_REPORT.md'}")


if __name__ == "__main__":
    main()
