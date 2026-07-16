# Allow running this file directly from the project root, e.g.
# python scripts/run_xxx.py
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pathlib import Path
import numpy as np
import pandas as pd


REGIME_PATH = Path(
    "data/processed/selection/theme_proxy_regime_history.csv"
)

PROXY_RETURNS_PATH = Path(
    "data/processed/research/theme_proxy_returns.parquet"
)

STOCK_RETURNS_PATH = Path(
    "data/processed/selection/stock_return_matrix.csv"
)

OUT_SUMMARY = Path(
    "data/processed/selection/bottom_base_exposure_summary.csv"
)

OUT_EVENTS = Path(
    "data/processed/selection/bottom_base_exposure_events.csv"
)

OUT_NAV = Path(
    "data/processed/selection/bottom_base_exposure_nav.csv"
)


ANCHOR_CODE = "600900.SH"

CYCLE_WEIGHT = 0.20
ANCHOR_WEIGHT = 0.60
RISK_FREE_WEIGHT = 0.20

RISK_FREE_RATE = 0.015
TRADING_DAYS = 252


def metrics(ret):
    ret = pd.Series(ret).dropna()

    if ret.empty:
        return {}

    nav = (1.0 + ret).cumprod()

    annual_return = (
        nav.iloc[-1] ** (
            TRADING_DAYS / len(ret)
        ) - 1.0
    )

    annual_vol = (
        ret.std(ddof=1)
        * np.sqrt(TRADING_DAYS)
    )

    excess_daily = (
        ret - RISK_FREE_RATE / TRADING_DAYS
    )

    sharpe = (
        excess_daily.mean()
        / ret.std(ddof=1)
        * np.sqrt(TRADING_DAYS)
        if ret.std(ddof=1) > 0
        else np.nan
    )

    downside = ret[
        ret < 0
    ].std(ddof=1)

    sortino = (
        excess_daily.mean()
        / downside
        * np.sqrt(TRADING_DAYS)
        if pd.notna(downside)
        and downside > 0
        else np.nan
    )

    drawdown = (
        nav / nav.cummax() - 1.0
    )

    max_drawdown = drawdown.min()

    calmar = (
        annual_return
        / abs(max_drawdown)
        if max_drawdown < 0
        else np.nan
    )

    return {
        "n_obs": len(ret),
        "annual_return": annual_return,
        "annual_vol": annual_vol,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_drawdown,
        "calmar": calmar,
        "final_nav": nav.iloc[-1],
    }


def main():

    regime = pd.read_csv(
        REGIME_PATH
    )

    regime["trade_date"] = pd.to_datetime(
        regime["trade_date"]
    )

    proxy = pd.read_parquet(
        PROXY_RETURNS_PATH
    )

    proxy.index = pd.to_datetime(
        proxy.index
    )

    stock_ret = pd.read_csv(
        STOCK_RETURNS_PATH
    )

    stock_ret["trade_date"] = pd.to_datetime(
        stock_ret["trade_date"]
    )

    stock_ret = (
        stock_ret
        .set_index("trade_date")
        .sort_index()
    )

    if ANCHOR_CODE not in stock_ret.columns:
        raise KeyError(
            f"Missing anchor {ANCHOR_CODE}"
        )

    anchor_ret = pd.to_numeric(
        stock_ret[ANCHOR_CODE],
        errors="coerce",
    )

    rf_daily = (
        (1.0 + RISK_FREE_RATE)
        ** (1.0 / TRADING_DAYS)
        - 1.0
    )

    summary_rows = []
    event_rows = []
    nav_rows = []

    for theme in proxy.columns:

        print(
            f"\n===== {theme.upper()} ====="
        )

        theme_regime = (
            regime[
                regime["theme"] == theme
            ]
            .copy()
            .sort_values("trade_date")
            .set_index("trade_date")
        )

        cycle_ret = pd.to_numeric(
            proxy[theme],
            errors="coerce",
        )

        frame = pd.concat(
            [
                cycle_ret.rename("cycle_ret"),
                anchor_ret.rename("anchor_ret"),
            ],
            axis=1,
        )

        frame = frame.join(
            theme_regime[
                [
                    "theme_regime",
                    "entry_eligible",
                    "exit_signal",
                ]
            ],
            how="left",
        )

        frame = frame.dropna(
            subset=[
                "cycle_ret",
                "anchor_ret",
            ]
        )

        frame["entry_eligible"] = (
            frame["entry_eligible"]
            .fillna(False)
            .astype(bool)
        )

        frame["exit_signal"] = (
            frame["exit_signal"]
            .fillna(False)
            .astype(bool)
        )

        in_position = False

        strategy_returns = []
        benchmark_returns = []

        nav = 1.0
        benchmark_nav = 1.0

        entry_date = None
        entry_nav = None

        for date, row in frame.iterrows():

            action = "HOLD"

            # -----------------------------------------------
            # ENTRY
            # -----------------------------------------------

            if (
                not in_position
                and row["entry_eligible"]
            ):
                in_position = True

                entry_date = date
                entry_nav = nav

                action = "ENTRY_BASE"

                event_rows.append({
                    "trade_date": date,
                    "theme": theme,
                    "action": action,
                    "theme_regime":
                        row["theme_regime"],
                    "nav": nav,
                })

            # -----------------------------------------------
            # EXIT
            # -----------------------------------------------

            elif (
                in_position
                and row["exit_signal"]
            ):
                in_position = False

                action = "EXIT_BASE"

                holding_return = (
                    nav / entry_nav - 1.0
                    if entry_nav is not None
                    else np.nan
                )

                event_rows.append({
                    "trade_date": date,
                    "theme": theme,
                    "action": action,
                    "theme_regime":
                        row["theme_regime"],
                    "nav": nav,
                    "entry_date": entry_date,
                    "holding_return":
                        holding_return,
                })

                entry_date = None
                entry_nav = None

            # -----------------------------------------------
            # PORTFOLIO RETURN
            # -----------------------------------------------

            if in_position:

                portfolio_ret = (
                    CYCLE_WEIGHT
                    * row["cycle_ret"]
                    + ANCHOR_WEIGHT
                    * row["anchor_ret"]
                    + RISK_FREE_WEIGHT
                    * rf_daily
                )

            else:

                portfolio_ret = (
                    (
                        CYCLE_WEIGHT
                        + ANCHOR_WEIGHT
                    )
                    * row["anchor_ret"]
                    + RISK_FREE_WEIGHT
                    * rf_daily
                )

            # benchmark:
            # never buy cycle

            benchmark_ret = (
                (
                    CYCLE_WEIGHT
                    + ANCHOR_WEIGHT
                )
                * row["anchor_ret"]
                + RISK_FREE_WEIGHT
                * rf_daily
            )

            strategy_returns.append(
                portfolio_ret
            )

            benchmark_returns.append(
                benchmark_ret
            )

            nav *= (
                1.0 + portfolio_ret
            )

            benchmark_nav *= (
                1.0 + benchmark_ret
            )

            nav_rows.append({
                "trade_date": date,
                "theme": theme,
                "in_position": in_position,
                "theme_regime":
                    row["theme_regime"],
                "portfolio_ret":
                    portfolio_ret,
                "benchmark_ret":
                    benchmark_ret,
                "nav": nav,
                "benchmark_nav":
                    benchmark_nav,
            })

        strategy_metrics = metrics(
            strategy_returns
        )

        benchmark_metrics = metrics(
            benchmark_returns
        )

        summary_rows.append({
            "theme": theme,
            "strategy":
                "BOTTOM_BASE_EXPOSURE",
            **strategy_metrics,
        })

        summary_rows.append({
            "theme": theme,
            "strategy":
                "ANCHOR_RF_BENCHMARK",
            **benchmark_metrics,
        })

        print(
            "strategy final nav:",
            round(
                strategy_metrics[
                    "final_nav"
                ],
                4,
            )
        )

        print(
            "benchmark final nav:",
            round(
                benchmark_metrics[
                    "final_nav"
                ],
                4,
            )
        )

    summary = pd.DataFrame(
        summary_rows
    )

    events = pd.DataFrame(
        event_rows
    )

    nav_df = pd.DataFrame(
        nav_rows
    )

    OUT_SUMMARY.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    summary.to_csv(
        OUT_SUMMARY,
        index=False,
        encoding="utf-8-sig",
    )

    events.to_csv(
        OUT_EVENTS,
        index=False,
        encoding="utf-8-sig",
    )

    nav_df.to_csv(
        OUT_NAV,
        index=False,
        encoding="utf-8-sig",
    )

    print(
        "\n===== SUMMARY ====="
    )

    print(
        summary
        .round(4)
        .to_string(index=False)
    )

    print(
        "\n===== ENTRY / EXIT EVENTS ====="
    )

    if events.empty:

        print(
            "NO EVENTS"
        )

    else:

        print(
            events
            .round(4)
            .to_string(index=False)
        )

    print(
        "\nsaved:",
        OUT_SUMMARY,
    )

    print(
        "saved:",
        OUT_EVENTS,
    )

    print(
        "saved:",
        OUT_NAV,
    )


if __name__ == "__main__":
    main()
