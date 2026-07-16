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

RETURNS_PATH = Path(
    "data/processed/selection/stock_return_matrix.csv"
)

CPPI_NAV_PATH = Path(
    "data/processed/selection/defensive_anchor_cppi_nav.csv"
)

CPPI_SUMMARY_PATH = Path(
    "data/processed/selection/defensive_anchor_cppi_summary.csv"
)

OUT_PATH = Path(
    "data/processed/selection/defensive_anchor_benchmark.csv"
)

TRADING_DAYS = 252
RISK_FREE_RATE = 0.015
RISK_FREE_DAILY = (
    (1 + RISK_FREE_RATE) ** (1 / TRADING_DAYS) - 1
)


def max_drawdown(ret):
    nav = (1 + ret).cumprod()

    return float(
        (
            nav / nav.cummax() - 1
        ).min()
    )


def annual_return(ret):
    ret = ret.dropna()

    if ret.empty:
        return np.nan

    nav = float(
        (1 + ret).prod()
    )

    years = len(ret) / TRADING_DAYS

    if years <= 0 or nav <= 0:
        return np.nan

    return (
        nav ** (1 / years)
        - 1
    )


def annual_vol(ret):
    ret = ret.dropna()

    if ret.empty:
        return np.nan

    return float(
        ret.std()
        * np.sqrt(TRADING_DAYS)
    )


def sharpe(ret):
    ret = ret.dropna()

    if ret.empty:
        return np.nan

    excess = (
        ret - RISK_FREE_DAILY
    )

    sd = excess.std()

    if sd == 0 or pd.isna(sd):
        return np.nan

    return float(
        excess.mean()
        / sd
        * np.sqrt(TRADING_DAYS)
    )


def sortino(ret):
    ret = ret.dropna()

    if ret.empty:
        return np.nan

    excess = (
        ret - RISK_FREE_DAILY
    )

    downside = excess[
        excess < 0
    ]

    sd = downside.std()

    if sd == 0 or pd.isna(sd):
        return np.nan

    return float(
        excess.mean()
        / sd
        * np.sqrt(TRADING_DAYS)
    )


def calmar(ret):
    dd = abs(
        max_drawdown(ret)
    )

    if dd == 0:
        return np.nan

    return float(
        annual_return(ret)
        / dd
    )


def metrics(ret):
    ret = ret.dropna()

    return {
        "n_obs": len(ret),
        "annual_return": annual_return(ret),
        "annual_vol": annual_vol(ret),
        "sharpe": sharpe(ret),
        "sortino": sortino(ret),
        "max_drawdown": max_drawdown(ret),
        "calmar": calmar(ret),
        "final_nav": float(
            (1 + ret).prod()
        ),
    }


def main():
    returns = pd.read_csv(
        RETURNS_PATH
    )

    cppi_nav = pd.read_csv(
        CPPI_NAV_PATH
    )

    cppi_summary = pd.read_csv(
        CPPI_SUMMARY_PATH
    )

    returns["trade_date"] = pd.to_datetime(
        returns["trade_date"]
    )

    cppi_nav["trade_date"] = pd.to_datetime(
        cppi_nav["trade_date"]
    )

    returns = (
        returns
        .set_index("trade_date")
        .sort_index()
    )

    rows = []

    for _, config in cppi_summary.iterrows():
        theme = config["theme"]
        cycle = config["cycle_ts_code"]
        anchor = config["anchor_ts_code"]

        pair_nav = cppi_nav[
            cppi_nav["theme"] == theme
        ].copy()

        pair_nav = (
            pair_nav
            .set_index("trade_date")
            .sort_index()
        )

        dates = pair_nav.index

        cycle_ret = (
            returns[cycle]
            .reindex(dates)
        )

        anchor_ret = (
            returns[anchor]
            .reindex(dates)
        )

        rf_ret = pd.Series(
            RISK_FREE_DAILY,
            index=dates,
        )

        benchmark = pd.DataFrame(
            {
                "cycle": cycle_ret,
                "anchor": anchor_ret,
                "risk_free": rf_ret,
            }
        ).dropna()

        benchmark["fixed_50_50"] = (
            0.50 * benchmark["cycle"]
            + 0.50 * benchmark["anchor"]
        )

        cppi_ret = (
            pair_nav["nav"]
            .pct_change()
            .reindex(
                benchmark.index
            )
        )

        strategies = {
            "CYCLE_ONLY":
                benchmark["cycle"],

            "ANCHOR_ONLY":
                benchmark["anchor"],

            "RISK_FREE_ONLY":
                benchmark["risk_free"],

            "FIXED_50_50":
                benchmark["fixed_50_50"],

            "DEFENSIVE_ANCHOR_CPPI":
                cppi_ret,
        }

        for strategy, ret in strategies.items():
            row = {
                "theme": theme,
                "cycle_ts_code": cycle,
                "anchor_ts_code": anchor,
                "strategy": strategy,
            }

            row.update(
                metrics(ret)
            )

            rows.append(row)

    result = pd.DataFrame(rows)

    result.to_csv(
        OUT_PATH,
        index=False,
        encoding="utf-8-sig",
    )

    print(
        "\n===== DEFENSIVE ANCHOR BENCHMARK ====="
    )

    display_cols = [
        "theme",
        "strategy",
        "annual_return",
        "annual_vol",
        "sharpe",
        "sortino",
        "max_drawdown",
        "calmar",
        "final_nav",
    ]

    for theme in result["theme"].unique():
        print(
            f"\n===== {theme.upper()} ====="
        )

        x = result[
            result["theme"] == theme
        ][display_cols]

        print(
            x.round(4)
            .to_string(index=False)
        )

    print(
        "\n===== CPPI VS FIXED 50/50 ====="
    )

    pivot = result.pivot(
        index="theme",
        columns="strategy",
        values=[
            "annual_return",
            "sharpe",
            "max_drawdown",
            "calmar",
        ],
    )

    for theme in pivot.index:
        try:
            cppi_return = pivot.loc[
                theme,
                (
                    "annual_return",
                    "DEFENSIVE_ANCHOR_CPPI",
                ),
            ]

            fixed_return = pivot.loc[
                theme,
                (
                    "annual_return",
                    "FIXED_50_50",
                ),
            ]

            cppi_sharpe = pivot.loc[
                theme,
                (
                    "sharpe",
                    "DEFENSIVE_ANCHOR_CPPI",
                ),
            ]

            fixed_sharpe = pivot.loc[
                theme,
                (
                    "sharpe",
                    "FIXED_50_50",
                ),
            ]

            cppi_dd = pivot.loc[
                theme,
                (
                    "max_drawdown",
                    "DEFENSIVE_ANCHOR_CPPI",
                ),
            ]

            fixed_dd = pivot.loc[
                theme,
                (
                    "max_drawdown",
                    "FIXED_50_50",
                ),
            ]

            print(
                f"\n{theme}"
            )

            print(
                "annual_return_delta:",
                round(
                    cppi_return
                    - fixed_return,
                    4,
                ),
            )

            print(
                "sharpe_delta:",
                round(
                    cppi_sharpe
                    - fixed_sharpe,
                    4,
                ),
            )

            print(
                "drawdown_improvement:",
                round(
                    cppi_dd
                    - fixed_dd,
                    4,
                ),
            )

        except KeyError:
            continue

    print(
        "\nsaved:",
        OUT_PATH,
    )


if __name__ == "__main__":
    main()
