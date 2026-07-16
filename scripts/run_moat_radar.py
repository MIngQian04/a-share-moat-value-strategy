"""Build the event-driven moat review queue for current holdings."""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_loader.announcement_store import normalize_announcements, refresh_announcements
from data_loader.tushare_client import TushareClient
from selection.moat_radar import build_announcement_alerts, build_financial_alerts, build_review_due_alerts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", help="YYYY-MM-DD; defaults to portfolio as-of date")
    parser.add_argument("--offline", action="store_true", help="use cached announcements only")
    parser.add_argument("--lookback-days", type=int, default=14)
    args = parser.parse_args()

    output_dir = PROJECT_ROOT / "outputs/barbell-strategy"
    holdings = pd.read_csv(output_dir / "target_portfolio.csv", encoding="utf-8-sig")
    registry = pd.read_csv(PROJECT_ROOT / "config/moat-thesis-registry.csv", encoding="utf-8-sig")
    summary = pd.read_csv(output_dir / "portfolio_summary.csv", encoding="utf-8-sig").iloc[0]
    as_of = pd.Timestamp(args.as_of or summary["as_of_date"]).normalize()
    start = as_of - pd.Timedelta(days=args.lookback_days)
    codes = holdings["ts_code"].dropna().astype(str).tolist()
    cache_path = PROJECT_ROOT / "data/processed/portfolio/announcements.csv"
    errors: list[str] = []
    succeeded: list[str] = []

    if args.offline:
        announcements = normalize_announcements(pd.read_csv(cache_path) if cache_path.exists() else None)
        announcement_status = "OFFLINE"
    else:
        try:
            client = TushareClient(data_dir=PROJECT_ROOT / "data/raw")
            announcements, succeeded, errors = refresh_announcements(
                client.pro, codes, start.strftime("%Y-%m-%d"), as_of.strftime("%Y-%m-%d"),
                cache_path, client.sleep_seconds,
            )
            announcement_status = "OK" if len(succeeded) == len(codes) else "PARTIAL" if succeeded else "UNAVAILABLE"
        except Exception as exc:
            announcements = normalize_announcements(pd.read_csv(cache_path) if cache_path.exists() else None)
            errors = [" ".join(str(exc).split())[:180]]
            announcement_status = "UNAVAILABLE"

    recent = announcements[
        pd.to_datetime(announcements["ann_date"], errors="coerce").between(start, as_of)
        & announcements["ts_code"].isin(codes)
    ]
    announcement_alerts = build_announcement_alerts(recent, as_of.strftime("%Y-%m-%d"))
    financial_alerts, financial_health = build_financial_alerts(
        holdings, PROJECT_ROOT / "data/raw/fundamental", as_of.strftime("%Y-%m-%d")
    )
    due_alerts = build_review_due_alerts(registry, as_of.strftime("%Y-%m-%d"))
    alerts = pd.concat([announcement_alerts, financial_alerts, due_alerts], ignore_index=True)
    alerts = alerts.drop_duplicates("alert_id", keep="last")

    alert_path = output_dir / "moat_radar_alerts.csv"
    if alert_path.exists() and not alerts.empty:
        old = pd.read_csv(alert_path, encoding="utf-8-sig")
        statuses = old.set_index("alert_id")["review_status"] if "review_status" in old else pd.Series(dtype=str)
        alerts["review_status"] = alerts["alert_id"].map(statuses).fillna(alerts["review_status"])
    alerts = alerts.sort_values(["alert_level", "alert_date"], ascending=[True, False]) if not alerts.empty else alerts
    alerts.to_csv(alert_path, index=False, encoding="utf-8-sig")

    pending = alerts[alerts["review_status"].eq("PENDING_REVIEW")] if not alerts.empty else alerts
    health = pd.DataFrame([{
        "as_of_date": as_of.strftime("%Y-%m-%d"),
        "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "announcement_status": announcement_status,
        "codes_requested": len(codes), "codes_succeeded": len(succeeded),
        "announcement_errors": " | ".join(errors),
        "announcement_rows_in_window": len(recent),
        "financial_status": "OK" if financial_health["codes_checked"] == len(codes) else "PARTIAL",
        "financial_codes_checked": financial_health["codes_checked"],
        "financial_missing_codes": "|".join(financial_health["missing_codes"]),
        "pending_alerts": len(pending),
        "high_alerts": int(pending["alert_level"].eq("HIGH").sum()) if not pending.empty else 0,
        "latest_announcement_date": recent["ann_date"].max() if not recent.empty else "",
    }])
    health.to_csv(output_dir / "moat_radar_health.csv", index=False, encoding="utf-8-sig")
    print(f"announcement_status={announcement_status} announcements={len(recent)} pending_alerts={len(pending)} high_alerts={int(health.iloc[0]['high_alerts'])}")


if __name__ == "__main__":
    main()
