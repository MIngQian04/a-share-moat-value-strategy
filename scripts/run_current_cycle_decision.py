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


NAV_PATH = Path(
    "data/processed/selection/"
    "cycle_base_sequence_cppi_nav.csv"
)

TRADES_PATH = Path(
    "data/processed/selection/"
    "cycle_base_sequence_cppi_trades.csv"
)

SUMMARY_PATH = Path(
    "data/processed/selection/"
    "cycle_base_sequence_cppi_summary.csv"
)

RANK1_CLOSE_PATH = Path(
    "data/processed/research/"
    "rank1_close.parquet"
)

OUT_CSV = Path(
    "data/processed/selection/"
    "today_cycle_decision.csv"
)

OUT_TXT = Path(
    "data/processed/selection/"
    "today_cycle_decision.txt"
)


RANK1_MAP = {
    "coal": "601001.SH",
    "copper": "600301.SH",
    "fertilizer": "600141.SH",
    "lithium": "300390.SZ",
    "oil": "603619.SH",
    "solar": "688390.SH",
    "steel": "000959.SZ",
}


def fmt_pct(x):
    if pd.isna(x):
        return "N/A"

    return f"{float(x) * 100:.2f}%"


def fmt_price(x):
    if pd.isna(x):
        return "N/A"

    return f"{float(x):.4f}"


def safe_float(x):
    try:
        if pd.isna(x):
            return np.nan

        return float(x)

    except Exception:
        return np.nan


def latest_theme_trade(
    trades,
    theme,
    actions=None,
):
    x = trades[
        trades["theme"] == theme
    ].copy()

    if actions is not None:
        x = x[
            x["action"].isin(actions)
        ]

    if x.empty:
        return None

    return x.sort_values(
        "trade_date"
    ).iloc[-1]


def main():
    nav = pd.read_csv(NAV_PATH)

    nav["trade_date"] = pd.to_datetime(
        nav["trade_date"]
    )

    nav = nav.sort_values(
        "trade_date"
    ).reset_index(drop=True)

    trades = pd.read_csv(TRADES_PATH)

    trades["trade_date"] = pd.to_datetime(
        trades["trade_date"]
    )

    trades = trades.sort_values(
        "trade_date"
    ).reset_index(drop=True)

    summary = pd.read_csv(SUMMARY_PATH)

    close = pd.read_parquet(
        RANK1_CLOSE_PATH
    )

    close.index = pd.to_datetime(
        close.index
    )

    close = close.sort_index()

    latest = nav.iloc[-1]

    as_of_date = latest["trade_date"]

    current_theme = latest.get(
        "current_theme"
    )

    cycle_weight = safe_float(
        latest.get("cycle_weight")
    )

    anchor_weight = safe_float(
        latest.get("anchor_weight")
    )

    risk_free_weight = safe_float(
        latest.get("risk_free_weight")
    )

    nav_value = safe_float(
        latest.get("nav")
    )

    cushion = safe_float(
        latest.get("cushion")
    )

    risk_expansion_open = bool(
        latest.get(
            "risk_expansion_open",
            False,
        )
    )

    volume_state = latest.get(
        "volume_state",
        "UNKNOWN",
    )

    step_weight = safe_float(
        latest.get("step_weight")
    )

    last_add_price = safe_float(
        latest.get("last_add_price")
    )

    cppi_weight = safe_float(
        latest.get("cppi_weight")
    )

    if (
        pd.isna(current_theme)
        or str(current_theme).lower() == "nan"
    ):
        current_theme = None

    rank1 = (
        RANK1_MAP.get(current_theme)
        if current_theme is not None
        else None
    )

    current_price = np.nan

    if (
        current_theme is not None
        and current_theme in close.columns
    ):
        price_series = (
            close[current_theme]
            .loc[:as_of_date]
            .dropna()
        )

        if not price_series.empty:
            current_price = float(
                price_series.iloc[-1]
            )

    active_entry = None

    if current_theme is not None:
        active_entry = latest_theme_trade(
            trades,
            current_theme,
            actions=["ENTER_BASE"],
        )

    theme_score = np.nan
    theme_regime = "UNKNOWN"

    if active_entry is not None:
        theme_score = safe_float(
            active_entry.get("score")
        )

        theme_regime = active_entry.get(
            "regime",
            "UNKNOWN",
        )

    last_bottom_volume = None

    if current_theme is not None:
        last_bottom_volume = (
            latest_theme_trade(
                trades,
                current_theme,
                actions=["BOTTOM_VOLUME"],
            )
        )

    bottom_volume_detected = False
    bottom_volume_date = pd.NaT
    amount_ratio = np.nan
    position_252 = np.nan

    if last_bottom_volume is not None:
        bottom_volume_date = (
            last_bottom_volume[
                "trade_date"
            ]
        )

        amount_ratio = safe_float(
            last_bottom_volume.get(
                "amount_ratio"
            )
        )

        position_252 = safe_float(
            last_bottom_volume.get(
                "position_252"
            )
        )

        if (
            active_entry is not None
            and bottom_volume_date
            >= active_entry["trade_date"]
        ):
            bottom_volume_detected = True

    confirm_actions = [
        "SEQUENCE_CONFIRMED_OPEN_STEP_RISK",
        "TIME_SURVIVED_ACCUMULATION_CONFIRMED",
    ]

    last_confirm = None

    if current_theme is not None:
        last_confirm = latest_theme_trade(
            trades,
            current_theme,
            actions=confirm_actions,
        )

    accumulation_confirmed = False
    confirmation_type = "NONE"
    confirmation_date = pd.NaT

    if last_confirm is not None:
        confirmation_date = (
            last_confirm["trade_date"]
        )

        if (
            active_entry is not None
            and confirmation_date
            >= active_entry["trade_date"]
        ):
            accumulation_confirmed = True

            confirmation_type = (
                last_confirm["action"]
            )

    last_drop = None

    if current_theme is not None:
        last_drop = latest_theme_trade(
            trades,
            current_theme,
            actions=[
                "DROP_EXPANSION_TO_BASE"
            ],
        )

    if (
        last_drop is not None
        and pd.notna(confirmation_date)
        and last_drop["trade_date"]
        > confirmation_date
    ):
        accumulation_confirmed = False
        confirmation_type = (
            "EXPANSION_DROPPED"
        )

    next_step_add_price = np.nan

    if (
        risk_expansion_open
        and pd.notna(last_add_price)
    ):
        next_step_add_price = (
            last_add_price * 1.10
        )

    if current_theme is None:
        position_state = "NO_CYCLE_POSITION"
        action = "STAY_DEFENSIVE"

        reason = (
            "No active cycle theme is currently held."
        )

    elif not risk_expansion_open:
        position_state = "BASE"

        if (
            active_entry is not None
            and active_entry["trade_date"]
            == as_of_date
        ):
            action = "BUILD_BASE"
        else:
            action = "HOLD_BASE"

        reason = (
            f"{current_theme.upper()} is the active "
            f"cycle theme in {theme_regime}. "
            "Base exposure is allowed, but expansion "
            "permission is closed."
        )

    else:
        position_state = "EXPANSION_OPEN"

        if (
            pd.notna(next_step_add_price)
            and pd.notna(current_price)
            and current_price
            >= next_step_add_price
        ):
            action = "STEP_ADD_READY"

            reason = (
                "Accumulation has been confirmed and "
                "the next price confirmation level "
                "has been reached."
            )

        else:
            action = "HOLD_CURRENT_WEIGHT"

            reason = (
                "Accumulation has been confirmed. "
                "Expansion permission is open, but "
                "the next step-add price has not "
                "been reached."
            )

    decision = {
        "as_of_date":
            as_of_date.strftime("%Y-%m-%d"),

        "selected_theme":
            current_theme,

        "rank1":
            rank1,

        "theme_regime":
            theme_regime,

        "theme_score":
            theme_score,

        "position_state":
            position_state,

        "action":
            action,

        "current_cycle_weight":
            cycle_weight,

        "target_cycle_weight":
            cycle_weight,

        "anchor_weight":
            anchor_weight,

        "risk_free_weight":
            risk_free_weight,

        "current_price":
            current_price,

        "bottom_volume_detected":
            bottom_volume_detected,

        "bottom_volume_date":
            (
                bottom_volume_date.strftime(
                    "%Y-%m-%d"
                )
                if pd.notna(
                    bottom_volume_date
                )
                else None
            ),

        "amount_ratio":
            amount_ratio,

        "position_252":
            position_252,

        "accumulation_confirmed":
            accumulation_confirmed,

        "confirmation_type":
            confirmation_type,

        "confirmation_date":
            (
                confirmation_date.strftime(
                    "%Y-%m-%d"
                )
                if pd.notna(
                    confirmation_date
                )
                else None
            ),

        "risk_expansion_open":
            risk_expansion_open,

        "step_weight":
            step_weight,

        "last_add_price":
            last_add_price,

        "next_step_add_price":
            next_step_add_price,

        "cppi_ceiling":
            cppi_weight,

        "portfolio_nav":
            nav_value,

        "cushion":
            cushion,

        "reason":
            reason,
    }

    result = pd.DataFrame(
        [decision]
    )

    OUT_CSV.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    result.to_csv(
        OUT_CSV,
        index=False,
        encoding="utf-8-sig",
    )

    lines = [
        "===== TODAY DECISION REPORT =====",
        "",
        f"AS OF DATE          : {decision['as_of_date']}",
        "",
        f"SELECTED THEME      : {str(current_theme).upper() if current_theme else 'NONE'}",
        f"RANK1               : {rank1 or 'N/A'}",
        "",
        f"THEME REGIME        : {theme_regime}",
        f"THEME SCORE         : {theme_score if pd.notna(theme_score) else 'N/A'}",
        "",
        f"POSITION STATE      : {position_state}",
        f"ACTION              : {action}",
        "",
        f"CYCLE WEIGHT        : {fmt_pct(cycle_weight)}",
        f"ANCHOR WEIGHT       : {fmt_pct(anchor_weight)}",
        f"RISK FREE WEIGHT    : {fmt_pct(risk_free_weight)}",
        "",
        f"CURRENT PRICE       : {fmt_price(current_price)}",
        "",
        f"BOTTOM VOLUME       : {bottom_volume_detected}",
        f"BOTTOM VOLUME DATE  : {decision['bottom_volume_date'] or 'N/A'}",
        f"AMOUNT RATIO        : {fmt_price(amount_ratio)}",
        f"POSITION 252        : {fmt_pct(position_252)}",
        "",
        f"ACCUM CONFIRMED     : {accumulation_confirmed}",
        f"CONFIRMATION TYPE   : {confirmation_type}",
        f"CONFIRMATION DATE   : {decision['confirmation_date'] or 'N/A'}",
        "",
        f"EXPANSION OPEN      : {risk_expansion_open}",
        f"STEP WEIGHT         : {fmt_pct(step_weight)}",
        f"LAST ADD PRICE      : {fmt_price(last_add_price)}",
        f"NEXT STEP PRICE     : {fmt_price(next_step_add_price)}",
        f"CPPI CEILING        : {fmt_pct(cppi_weight)}",
        "",
        f"PORTFOLIO NAV       : {fmt_price(nav_value)}",
        f"CUSHION             : {fmt_pct(cushion)}",
        "",
        "DECISION REASON:",
        reason,
        "",
        "=================================",
    ]

    report = "\n".join(lines)

    OUT_TXT.write_text(
        report,
        encoding="utf-8",
    )

    print()
    print(report)

    print()
    print("saved:", OUT_CSV)
    print("saved:", OUT_TXT)


if __name__ == "__main__":
    main()
