from __future__ import annotations

import time
from pathlib import Path

import pandas as pd


ANNOUNCEMENT_COLUMNS = ["ann_date", "ts_code", "name", "title", "url", "rec_time"]


def normalize_announcements(frame: pd.DataFrame | None) -> pd.DataFrame:
    """Return a stable, deduplicated announcement cache schema."""
    if frame is None or frame.empty:
        return pd.DataFrame(columns=ANNOUNCEMENT_COLUMNS)
    out = frame.copy()
    for column in ANNOUNCEMENT_COLUMNS:
        if column not in out:
            out[column] = ""
        out[column] = out[column].fillna("").astype(str).str.strip()
    out["ann_date"] = pd.to_datetime(out["ann_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    out = out[out["ann_date"].notna() & out["ts_code"].ne("") & out["title"].ne("")]
    return (
        out[ANNOUNCEMENT_COLUMNS]
        .drop_duplicates(["ts_code", "ann_date", "title", "url"], keep="last")
        .sort_values(["ann_date", "ts_code", "title"], ascending=[False, True, True])
        .reset_index(drop=True)
    )


def refresh_announcements(
    pro,
    codes: list[str],
    start_date: str,
    end_date: str,
    destination: Path,
    sleep_seconds: float = 0.25,
) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Refresh official company announcements without erasing a good cache on failure.

    Returns the merged cache, successful codes, and sanitized per-code errors. The
    caller must treat an all-code failure as unavailable data, not as zero events.
    """
    cached = normalize_announcements(pd.read_csv(destination) if destination.exists() else None)
    frames: list[pd.DataFrame] = []
    succeeded: list[str] = []
    errors: list[str] = []
    for code in codes:
        try:
            result = pro.anns_d(
                ts_code=code,
                start_date=pd.Timestamp(start_date).strftime("%Y%m%d"),
                end_date=pd.Timestamp(end_date).strftime("%Y%m%d"),
                fields=",".join(ANNOUNCEMENT_COLUMNS),
            )
            frames.append(normalize_announcements(result))
            succeeded.append(code)
        except Exception as exc:  # provider permission and network errors are surfaced in health output
            message = " ".join(str(exc).split())[:180]
            errors.append(f"{code}: {message}")
        time.sleep(sleep_seconds)

    fresh = normalize_announcements(pd.concat(frames, ignore_index=True) if frames else None)
    merged = normalize_announcements(pd.concat([cached, fresh], ignore_index=True))
    destination.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(destination, index=False, encoding="utf-8-sig")
    return merged, succeeded, errors
