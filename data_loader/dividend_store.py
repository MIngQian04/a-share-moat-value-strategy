from __future__ import annotations

import time
from pathlib import Path

import pandas as pd


DIVIDEND_FIELDS = (
    "ts_code,end_date,ann_date,div_proc,stk_div,stk_bo_rate,stk_co_rate,"
    "cash_div,cash_div_tax,record_date,ex_date,pay_date,div_listdate,imp_ann_date"
)
DIVIDEND_COLUMNS = DIVIDEND_FIELDS.split(",")


def _date_text(values: pd.Series) -> pd.Series:
    digits = values.fillna("").astype(str).str.replace(r"\.0$", "", regex=True).str.replace(r"\D", "", regex=True)
    parsed = pd.to_datetime(digits.where(digits.str.len().eq(8)), format="%Y%m%d", errors="coerce")
    return parsed.dt.strftime("%Y-%m-%d").fillna("")


def normalize_dividend_events(frame: pd.DataFrame) -> pd.DataFrame:
    """Keep implemented, dated corporate-action records in a stable schema."""
    out = frame.copy()
    for column in DIVIDEND_COLUMNS:
        if column not in out:
            out[column] = "" if column not in {"stk_div", "stk_bo_rate", "stk_co_rate", "cash_div", "cash_div_tax"} else 0.0
    out = out[DIVIDEND_COLUMNS]
    out["div_proc"] = out["div_proc"].fillna("").astype(str)
    out = out[out["div_proc"].str.contains("实施", na=False)].copy()
    for column in ["end_date", "ann_date", "record_date", "ex_date", "pay_date", "div_listdate", "imp_ann_date"]:
        out[column] = _date_text(out[column])
    for column in ["stk_div", "stk_bo_rate", "stk_co_rate", "cash_div", "cash_div_tax"]:
        out[column] = pd.to_numeric(out[column], errors="coerce").fillna(0.0)
    out = out[out["ex_date"].ne("")].copy()
    key = ["ts_code", "end_date", "ex_date", "cash_div", "cash_div_tax", "stk_div"]
    return out.drop_duplicates(key, keep="last").sort_values(["ex_date", "ts_code"]).reset_index(drop=True)


def refresh_dividend_events(
    pro,
    codes: list[str],
    destination: Path,
    sleep_seconds: float = 0.0,
) -> tuple[pd.DataFrame, list[str]]:
    """Refresh implemented dividend events for held securities without dropping cached history."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    cached = pd.read_csv(destination) if destination.exists() else pd.DataFrame(columns=DIVIDEND_COLUMNS)
    frames = [cached]
    errors: list[str] = []
    for code in sorted(set(str(value) for value in codes if str(value))):
        try:
            result = pro.dividend(ts_code=code, fields=DIVIDEND_FIELDS)
            if result is not None and not result.empty:
                frames.append(result)
        except Exception as exc:
            errors.append(f"{code}:{type(exc).__name__}")
        if sleep_seconds:
            time.sleep(sleep_seconds)
    combined = normalize_dividend_events(pd.concat(frames, ignore_index=True, sort=False))
    combined.to_csv(destination, index=False, encoding="utf-8-sig")
    return combined, errors
