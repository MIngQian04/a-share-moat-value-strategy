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

CLOSE_PATH = Path("data/processed/selection/pair_close_matrix.csv")
RETURNS_PATH = Path("data/processed/selection/stock_return_matrix.csv")
PAIRS_PATH = Path("data/processed/selection/complement_pairs.csv")

OUT_SUMMARY = Path(
    "data/processed/selection/global_cppi_multicycle_summary.csv"
)

OUT_NAV = Path(
    "data/processed/selection/global_cppi_multicycle_nav.csv"
)

OUT_WEIGHTS = Path(
    "data/processed/selection/global_cppi_multicycle_weights.csv"
)

TRADING_DAYS = 252

ANCHOR = "600900.SH"

RISK_FREE_RATE = 0.015

RISK_FREE_DAILY = (
    (1 + RISK_FREE_RATE) ** (1 / TRADING_DAYS) - 1
)

# ============================================================
# Strategic Cycle Base Exposure
# ============================================================

BASE_TOTAL_CYCLE_WEIGHT = 0.10

# ============================================================
# Global CPPI Extra Risk Budget
# ============================================================

MAX_DRAWDOWN_LIMIT = 0.20

CPPI_MULTIPLIER = 3.0

MAX_EXTRA_CYCLE_WEIGHT = 0.50

MAX_TOTAL_CYCLE_WEIGHT = (
    BASE_TOTAL_CYCLE_WEIGHT
    + MAX_EXTRA_CYCLE_WEIGHT
)

# ============================================================
# Defensive Sleeve
# ============================================================

ANCHOR_DEFENSIVE_WEIGHT = 0.80

# ============================================================
# Reversal Signal
# ============================================================

LOW_POSITION_THRESHOLD = 0.30

THREE_DAY_RETURN_THRESHOLD = 0.05


def max_drawdown(ret):

    nav = (1 + ret).cumprod()

    return float(
        (
            nav / nav.cummax()
            - 1
        ).min()
    )


def annual_return(ret):

    ret = ret.dropna()

    if ret.empty:
        return np.nan

    nav = float(
        (1 + ret).prod()
    )

    years = (
        len(ret)
        / TRADING_DAYS
    )

    if years <= 0 or nav <= 0:
        return np.nan

    return (
        nav ** (1 / years)
        - 1
    )


def annual_vol(ret):

    ret = ret.dropna()

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

        "annual_return":
            annual_return(ret),

        "annual_vol":
            annual_vol(ret),

        "sharpe":
            sharpe(ret),

        "sortino":
            sortino(ret),

        "max_drawdown":
            max_drawdown(ret),

        "calmar":
            calmar(ret),

        "final_nav":
            float(
                (1 + ret).prod()
            ),
    }


def build_reversal_signal(close_series):

    df = pd.DataFrame(
        {
            "close": close_series
        }
    ).dropna()

    df["low_252"] = (
        df["close"]
        .rolling(
            252,
            min_periods=120,
        )
        .min()
    )

    df["high_252"] = (
        df["close"]
        .rolling(
            252,
            min_periods=120,
        )
        .max()
    )

    df["position_252"] = (

        df["close"]
        - df["low_252"]

    ) / (

        df["high_252"]
        - df["low_252"]

    )

    df["up_day"] = (

        df["close"]
        > df["close"].shift(1)

    )

    df["three_up"] = (

        df["up_day"]

        & df["up_day"].shift(1)

        & df["up_day"].shift(2)

    )

    df["three_day_return"] = (

        df["close"]
        / df["close"].shift(3)
        - 1

    )

    df["low_position_gate"] = (

        df["position_252"]
        .shift(3)

        <= LOW_POSITION_THRESHOLD

    )

    df["reversal_signal"] = (

        df["low_position_gate"]

        & df["three_up"]

        & (
            df["three_day_return"]
            >= THREE_DAY_RETURN_THRESHOLD
        )

    )

    return df["reversal_signal"]


def main():

    close = pd.read_csv(
        CLOSE_PATH
    )

    returns = pd.read_csv(
        RETURNS_PATH
    )

    pairs = pd.read_csv(
        PAIRS_PATH
    )

    close["trade_date"] = pd.to_datetime(
        close["trade_date"]
    )

    returns["trade_date"] = pd.to_datetime(
        returns["trade_date"]
    )

    close = (
        close
        .set_index("trade_date")
        .sort_index()
    )

    returns = (
        returns
        .set_index("trade_date")
        .sort_index()
    )

    cycles = (

        pairs[
            [
                "theme",
                "cycle_ts_code",
            ]
        ]

        .drop_duplicates()

        .sort_values("theme")

        .reset_index(drop=True)

    )

    cycle_codes = [

        code

        for code in cycles[
            "cycle_ts_code"
        ].tolist()

        if (
            code in returns.columns
            and code in close.columns
        )

    ]

    if ANCHOR not in returns.columns:

        raise RuntimeError(
            f"Missing anchor return data: {ANCHOR}"
        )

    theme_map = dict(

        zip(

            cycles["cycle_ts_code"],

            cycles["theme"],

        )

    )

    common_index = returns.index

    for code in (
        cycle_codes
        + [ANCHOR]
    ):

        common_index = (

            common_index
            .intersection(
                returns[
                    code
                ]
                .dropna()
                .index
            )

        )

    common_index = (
        common_index
        .sort_values()
    )

    # ========================================================
    # Reversal Signals
    # ========================================================

    reversal_df = pd.DataFrame(
        index=common_index
    )

    for code in cycle_codes:

        signal = build_reversal_signal(
            close[code]
        )

        reversal_df[code] = (

            signal
            .reindex(common_index)
            .fillna(False)

        )

    # ========================================================
    # Persistent Cycle State
    # ========================================================

    cycle_active = {

        code: False

        for code in cycle_codes

    }

    # Reversal opens tactical risk gate.
    # V1 does not automatically close the gate.
    #
    # Strategic base exposure always remains.

    nav = 1.0

    peak = 1.0

    nav_rows = []

    weight_rows = []

    base_per_cycle = (

        BASE_TOTAL_CYCLE_WEIGHT
        / len(cycle_codes)

    )

    for dt in common_index:

        # ----------------------------------------------------
        # Update Tactical Cycle States
        # ----------------------------------------------------

        for code in cycle_codes:

            reversal = bool(
                reversal_df.loc[
                    dt,
                    code,
                ]
            )

            if reversal:

                cycle_active[
                    code
                ] = True

        active_cycles = [

            code

            for code, active
            in cycle_active.items()

            if active

        ]

        # ----------------------------------------------------
        # Global CPPI
        # ----------------------------------------------------

        peak = max(
            peak,
            nav,
        )

        floor = (

            peak
            * (
                1
                - MAX_DRAWDOWN_LIMIT
            )

        )

        cushion = max(

            (
                nav
                - floor
            )
            / nav,

            0.0,

        )

        extra_cycle_budget = min(

            MAX_EXTRA_CYCLE_WEIGHT,

            max(

                0.0,

                CPPI_MULTIPLIER
                * cushion,

            ),

        )

        # Extra risk only goes to activated cycles

        extra_weights = {

            code: 0.0

            for code in cycle_codes

        }

        if active_cycles:

            extra_per_cycle = (

                extra_cycle_budget
                / len(active_cycles)

            )

            for code in active_cycles:

                extra_weights[
                    code
                ] = extra_per_cycle

        # ----------------------------------------------------
        # Final Cycle Weights
        # ----------------------------------------------------

        cycle_weights = {}

        for code in cycle_codes:

            cycle_weights[
                code
            ] = (

                base_per_cycle

                + extra_weights[
                    code
                ]

            )

        actual_cycle_weight = sum(

            cycle_weights.values()

        )

        actual_cycle_weight = min(

            actual_cycle_weight,

            MAX_TOTAL_CYCLE_WEIGHT,

        )

        # ----------------------------------------------------
        # Defensive Sleeve
        # ----------------------------------------------------

        defensive_weight = (

            1.0
            - actual_cycle_weight

        )

        anchor_weight = (

            defensive_weight
            * ANCHOR_DEFENSIVE_WEIGHT

        )

        rf_weight = (

            defensive_weight
            * (
                1
                - ANCHOR_DEFENSIVE_WEIGHT
            )

        )

        # ----------------------------------------------------
        # Portfolio Return
        # ----------------------------------------------------

        portfolio_ret = 0.0

        for code, weight in cycle_weights.items():

            portfolio_ret += (

                weight
                * returns.loc[
                    dt,
                    code,
                ]

            )

        portfolio_ret += (

            anchor_weight
            * returns.loc[
                dt,
                ANCHOR,
            ]

        )

        portfolio_ret += (

            rf_weight
            * RISK_FREE_DAILY

        )

        nav = (

            nav
            * (
                1
                + portfolio_ret
            )

        )

        # ----------------------------------------------------
        # NAV Log
        # ----------------------------------------------------

        nav_rows.append({

            "trade_date": dt,

            "portfolio_ret":
                portfolio_ret,

            "nav":
                nav,

            "peak_nav":
                peak,

            "floor_nav":
                floor,

            "cushion":
                cushion,

            "base_cycle_weight":
                BASE_TOTAL_CYCLE_WEIGHT,

            "extra_cycle_budget":
                extra_cycle_budget,

            "actual_cycle_weight":
                actual_cycle_weight,

            "anchor_weight":
                anchor_weight,

            "risk_free_weight":
                rf_weight,

            "num_active_cycles":
                len(active_cycles),

            "active_cycles":
                "|".join(
                    active_cycles
                ),

        })

        # ----------------------------------------------------
        # Weight Log
        # ----------------------------------------------------

        for code in cycle_codes:

            weight_rows.append({

                "trade_date":
                    dt,

                "theme":
                    theme_map.get(code),

                "cycle_ts_code":
                    code,

                "base_weight":
                    base_per_cycle,

                "extra_weight":
                    extra_weights[code],

                "total_weight":
                    cycle_weights[code],

                "cycle_active":
                    cycle_active[code],

                "reversal_signal":
                    bool(
                        reversal_df.loc[
                            dt,
                            code,
                        ]
                    ),

            })

        weight_rows.append({

            "trade_date":
                dt,

            "theme":
                "DEFENSIVE_ANCHOR",

            "cycle_ts_code":
                ANCHOR,

            "base_weight":
                0.0,

            "extra_weight":
                0.0,

            "total_weight":
                anchor_weight,

            "cycle_active":
                False,

            "reversal_signal":
                False,

        })

        weight_rows.append({

            "trade_date":
                dt,

            "theme":
                "RISK_FREE",

            "cycle_ts_code":
                "RISK_FREE_1.5%",

            "base_weight":
                0.0,

            "extra_weight":
                0.0,

            "total_weight":
                rf_weight,

            "cycle_active":
                False,

            "reversal_signal":
                False,

        })

    # ========================================================
    # Outputs
    # ========================================================

    nav_df = pd.DataFrame(
        nav_rows
    )

    weights_df = pd.DataFrame(
        weight_rows
    )

    ret = (

        nav_df

        .set_index(
            "trade_date"
        )

        ["portfolio_ret"]

    )

    summary = pd.DataFrame([{

        "strategy":
            "GLOBAL_BASE_PLUS_REVERSAL_CPPI",

        "anchor":
            ANCHOR,

        "risk_free_rate":
            RISK_FREE_RATE,

        "base_total_cycle_weight":
            BASE_TOTAL_CYCLE_WEIGHT,

        "max_extra_cycle_weight":
            MAX_EXTRA_CYCLE_WEIGHT,

        "max_total_cycle_weight":
            MAX_TOTAL_CYCLE_WEIGHT,

        "max_drawdown_limit":
            MAX_DRAWDOWN_LIMIT,

        "cppi_multiplier":
            CPPI_MULTIPLIER,

        "avg_actual_cycle_weight":
            nav_df[
                "actual_cycle_weight"
            ].mean(),

        "max_actual_cycle_weight":
            nav_df[
                "actual_cycle_weight"
            ].max(),

        "avg_anchor_weight":
            nav_df[
                "anchor_weight"
            ].mean(),

        "avg_risk_free_weight":
            nav_df[
                "risk_free_weight"
            ].mean(),

        "avg_active_cycles":
            nav_df[
                "num_active_cycles"
            ].mean(),

        "max_active_cycles":
            nav_df[
                "num_active_cycles"
            ].max(),

        **metrics(ret),

    }])

    OUT_SUMMARY.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    summary.to_csv(
        OUT_SUMMARY,
        index=False,
        encoding="utf-8-sig",
    )

    nav_df.to_csv(
        OUT_NAV,
        index=False,
        encoding="utf-8-sig",
    )

    weights_df.to_csv(
        OUT_WEIGHTS,
        index=False,
        encoding="utf-8-sig",
    )

    print(
        "\n===== GLOBAL BASE + REVERSAL CPPI SUMMARY ====="
    )

    print(
        summary
        .round(4)
        .to_string(index=False)
    )

    print(
        "\n===== ACTIVE CYCLE DAYS ====="
    )

    print(
        nav_df[
            "num_active_cycles"
        ]
        .value_counts()
        .sort_index()
        .to_string()
    )

    print(
        "\n===== AVERAGE CYCLE WEIGHTS ====="
    )

    cycle_only_weights = weights_df[
        weights_df["theme"].isin(
            cycles["theme"]
        )
    ]

    avg_weights = (

        cycle_only_weights

        .groupby(
            [
                "theme",
                "cycle_ts_code",
            ]
        )

        [
            [
                "base_weight",
                "extra_weight",
                "total_weight",
            ]
        ]

        .mean()

        .reset_index()

    )

    print(
        avg_weights
        .round(4)
        .to_string(index=False)
    )

    print(
        "\nsaved:",
        OUT_SUMMARY,
    )

    print(
        "saved:",
        OUT_NAV,
    )

    print(
        "saved:",
        OUT_WEIGHTS,
    )


if __name__ == "__main__":
    main()
