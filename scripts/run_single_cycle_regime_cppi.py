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


CLOSE_PATH = Path(
    "data/processed/selection/pair_close_matrix.csv"
)

RETURNS_PATH = Path(
    "data/processed/selection/stock_return_matrix.csv"
)

FINAL_PATH = Path(
    "data/processed/selection/final_candidates.csv"
)

OUT_SUMMARY = Path(
    "data/processed/selection/single_cycle_regime_cppi_summary.csv"
)

OUT_NAV = Path(
    "data/processed/selection/single_cycle_regime_cppi_nav.csv"
)

OUT_TRADES = Path(
    "data/processed/selection/single_cycle_regime_cppi_trades.csv"
)


TRADING_DAYS = 252


# ============================================================
# Portfolio
# ============================================================

ANCHOR = "600900.SH"

RISK_FREE_RATE = 0.015

RISK_FREE_DAILY = (
    (1 + RISK_FREE_RATE)
    ** (1 / TRADING_DAYS)
    - 1
)


# ============================================================
# Cycle Selector
# ============================================================

ENTRY_POSITION_THRESHOLD = 0.30

EXIT_POSITION_THRESHOLD = 0.80


# ============================================================
# Cycle Exposure
# ============================================================

BASE_CYCLE_WEIGHT = 0.20

MAX_CYCLE_WEIGHT = 0.60


# ============================================================
# CPPI
# ============================================================

MAX_DRAWDOWN_LIMIT = 0.20

CPPI_MULTIPLIER = 3.0


# ============================================================
# Defensive Sleeve
# ============================================================

ANCHOR_DEFENSIVE_WEIGHT = 0.80


# ============================================================
# Reversal
# ============================================================

THREE_DAY_RETURN_THRESHOLD = 0.05


def max_drawdown(ret):

    nav = (1 + ret).cumprod()

    return float(
        (
            nav
            / nav.cummax()
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

    excess = (
        ret
        - RISK_FREE_DAILY
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

    excess = (
        ret
        - RISK_FREE_DAILY
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


def metrics(ret):

    ret = ret.dropna()

    dd = max_drawdown(ret)

    ann = annual_return(ret)

    return {

        "n_obs":
            len(ret),

        "annual_return":
            ann,

        "annual_vol":
            annual_vol(ret),

        "sharpe":
            sharpe(ret),

        "sortino":
            sortino(ret),

        "max_drawdown":
            dd,

        "calmar":
            ann / abs(dd)
            if dd != 0
            else np.nan,

        "final_nav":
            float(
                (1 + ret).prod()
            ),
    }


def build_cycle_features(close):

    features = {}

    for code in close.columns:

        s = close[code]

        low_252 = (
            s
            .rolling(
                252,
                min_periods=120,
            )
            .min()
        )

        high_252 = (
            s
            .rolling(
                252,
                min_periods=120,
            )
            .max()
        )

        position = (

            (
                s
                - low_252
            )

            /

            (
                high_252
                - low_252
            )

        )

        up_day = (
            s
            > s.shift(1)
        )

        three_up = (

            up_day

            & up_day.shift(1)

            & up_day.shift(2)

        )

        three_day_return = (

            s
            / s.shift(3)
            - 1

        )

        reversal = (

            (
                position.shift(3)
                <= ENTRY_POSITION_THRESHOLD
            )

            & three_up

            & (
                three_day_return
                >= THREE_DAY_RETURN_THRESHOLD
            )

        )

        features[code] = pd.DataFrame({

            "position_252":
                position,

            "reversal":
                reversal,

        })

    return features


def main():

    close = pd.read_csv(
        CLOSE_PATH
    )

    returns = pd.read_csv(
        RETURNS_PATH
    )

    final = pd.read_csv(
        FINAL_PATH
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


    rank1 = (

        final[
            final["assembly_rank"] == 1
        ]

        [
            [
                "theme",
                "ts_code",
            ]
        ]

        .drop_duplicates()

    )


    theme_map = dict(

        zip(

            rank1["ts_code"],

            rank1["theme"],

        )

    )


    cycle_codes = [

        code

        for code
        in rank1["ts_code"]

        if (
            code in close.columns
            and code in returns.columns
        )

    ]


    if ANCHOR not in returns.columns:

        raise RuntimeError(
            f"Missing anchor: {ANCHOR}"
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


    features = build_cycle_features(

        close[
            cycle_codes
        ]

    )


    # ========================================================
    # Portfolio State
    # ========================================================

    nav = 1.0

    peak_nav = 1.0


    current_cycle = None

    reversal_active = False


    nav_rows = []

    trade_rows = []


    for dt in common_index:


        # ====================================================
        # Select Cycle
        # ====================================================

        if current_cycle is None:

            candidates = []


            for code in cycle_codes:

                position = (

                    features[
                        code
                    ]

                    ["position_252"]

                    .reindex(
                        [dt]
                    )

                    .iloc[0]

                )


                if (

                    pd.notna(position)

                    and position
                    <= ENTRY_POSITION_THRESHOLD

                ):

                    candidates.append(

                        (
                            code,
                            position,
                        )

                    )


            if candidates:

                candidates.sort(

                    key=lambda x: x[1]

                )


                current_cycle = (
                    candidates[0][0]
                )


                reversal_active = False


                trade_rows.append({

                    "trade_date":
                        dt,

                    "action":
                        "SELECT_CYCLE",

                    "theme":
                        theme_map.get(
                            current_cycle
                        ),

                    "cycle_ts_code":
                        current_cycle,

                    "position_252":
                        candidates[0][1],

                    "nav":
                        nav,

                })


        # ====================================================
        # Current Cycle State
        # ====================================================

        cycle_position = np.nan

        reversal_signal = False


        if current_cycle is not None:

            cycle_position = (

                features[
                    current_cycle
                ]

                ["position_252"]

                .reindex(
                    [dt]
                )

                .iloc[0]

            )


            reversal_signal = bool(

                features[
                    current_cycle
                ]

                ["reversal"]

                .reindex(
                    [dt]
                )

                .fillna(False)

                .iloc[0]

            )


            if (

                reversal_signal

                and not reversal_active

            ):

                reversal_active = True


                trade_rows.append({

                    "trade_date":
                        dt,

                    "action":
                        "REVERSAL_CONFIRMED",

                    "theme":
                        theme_map.get(
                            current_cycle
                        ),

                    "cycle_ts_code":
                        current_cycle,

                    "position_252":
                        cycle_position,

                    "nav":
                        nav,

                })


        # ====================================================
        # Global CPPI
        # ====================================================

        peak_nav = max(

            peak_nav,

            nav,

        )


        floor_nav = (

            peak_nav

            * (
                1
                - MAX_DRAWDOWN_LIMIT
            )

        )


        cushion = max(

            (
                nav
                - floor_nav
            )

            / nav,

            0.0,

        )


        cppi_cycle_weight = min(

            MAX_CYCLE_WEIGHT,

            CPPI_MULTIPLIER
            * cushion,

        )


        # ====================================================
        # Cycle Weight
        # ====================================================

        if current_cycle is None:

            cycle_weight = 0.0


        elif reversal_active:

            cycle_weight = max(

                BASE_CYCLE_WEIGHT,

                cppi_cycle_weight,

            )


        else:

            cycle_weight = (
                BASE_CYCLE_WEIGHT
            )


        # ====================================================
        # Defensive Sleeve
        # ====================================================

        defensive_weight = (

            1.0
            - cycle_weight

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


        # ====================================================
        # Portfolio Return
        # ====================================================

        portfolio_ret = 0.0


        if current_cycle is not None:

            portfolio_ret += (

                cycle_weight

                * returns.loc[
                    dt,
                    current_cycle,
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


        # ====================================================
        # NAV Log
        # ====================================================

        nav_rows.append({

            "trade_date":
                dt,

            "portfolio_ret":
                portfolio_ret,

            "nav":
                nav,

            "peak_nav":
                peak_nav,

            "floor_nav":
                floor_nav,

            "cushion":
                cushion,

            "current_theme":
                theme_map.get(
                    current_cycle
                )
                if current_cycle
                else None,

            "current_cycle":
                current_cycle,

            "cycle_position_252":
                cycle_position,

            "reversal_signal":
                reversal_signal,

            "reversal_active":
                reversal_active,

            "cycle_weight":
                cycle_weight,

            "anchor_weight":
                anchor_weight,

            "risk_free_weight":
                rf_weight,

        })


        # ====================================================
        # Cycle Exit
        # ====================================================

        if (

            current_cycle is not None

            and pd.notna(
                cycle_position
            )

            and cycle_position
            >= EXIT_POSITION_THRESHOLD

        ):


            trade_rows.append({

                "trade_date":
                    dt,

                "action":
                    "EXIT_CYCLE",

                "theme":
                    theme_map.get(
                        current_cycle
                    ),

                "cycle_ts_code":
                    current_cycle,

                "position_252":
                    cycle_position,

                "nav":
                    nav,

            })


            current_cycle = None

            reversal_active = False


    # ========================================================
    # Outputs
    # ========================================================

    nav_df = pd.DataFrame(
        nav_rows
    )


    trades_df = pd.DataFrame(
        trade_rows
    )


    ret = nav_df[
        "portfolio_ret"
    ]


    summary = pd.DataFrame([{

        "strategy":
            "SINGLE_CYCLE_REGIME_CPPI",

        "base_cycle_weight":
            BASE_CYCLE_WEIGHT,

        "max_cycle_weight":
            MAX_CYCLE_WEIGHT,

        "entry_position_threshold":
            ENTRY_POSITION_THRESHOLD,

        "exit_position_threshold":
            EXIT_POSITION_THRESHOLD,

        "avg_cycle_weight":
            nav_df[
                "cycle_weight"
            ].mean(),

        "max_cycle_weight_realized":
            nav_df[
                "cycle_weight"
            ].max(),

        "avg_anchor_weight":
            nav_df[
                "anchor_weight"
            ].mean(),

        "avg_risk_free_weight":
            nav_df[
                "risk_free_weight"
            ].mean(),

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


    trades_df.to_csv(

        OUT_TRADES,

        index=False,

        encoding="utf-8-sig",

    )


    print(

        "\n===== SINGLE CYCLE REGIME CPPI SUMMARY ====="

    )


    print(

        summary

        .round(4)

        .to_string(
            index=False
        )

    )


    print(

        "\n===== CYCLE SELECTION HISTORY ====="

    )


    print(

        trades_df

        .round(4)

        .to_string(
            index=False
        )

    )


    print(

        "\n===== THEME HOLDING DAYS ====="

    )


    print(

        nav_df[
            "current_theme"
        ]

        .value_counts(

            dropna=False

        )

        .to_string()

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

        OUT_TRADES,

    )


if __name__ == "__main__":

    main()
