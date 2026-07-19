"""Build sanitized, committed documentation snapshots from local barbell outputs.

This helper reads generated local outputs but writes only public, aggregate or
research-queue data. It never reads target weights, fills, credentials or
browser-local records. Run it after a completed barbell refresh when updating
the README's status and ranking preview.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "outputs/barbell-strategy"
DEFAULT_DOCS = ROOT / "docs"
RANKING_ROWS = 8


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"required output is missing: {path}")
    return pd.read_csv(path)


def as_int(value) -> int:
    return int(pd.to_numeric(value, errors="raise"))


def build_snapshot(output_dir: Path, docs_dir: Path, ranking_rows: int = RANKING_ROWS) -> None:
    summary = read_csv(output_dir / "portfolio_summary.csv")
    all_anchors = read_csv(output_dir / "anchor_screen.csv")
    nav = read_csv(output_dir / "portfolio_nav_history.csv")
    registry = read_csv(ROOT / "config/moat-thesis-registry.csv")
    radar_health = read_csv(output_dir / "moat_radar_health.csv")

    if summary.empty:
        raise ValueError("portfolio_summary.csv has no rows")
    current = summary.iloc[0]
    as_of = str(current["as_of_date"])
    anchors = all_anchors.copy()
    anchors["anchor_score"] = pd.to_numeric(anchors["anchor_score"], errors="coerce")
    anchors = anchors.sort_values(["anchor_score", "ts_code"], ascending=[False, True]).head(ranking_rows).copy()
    anchors.insert(0, "rank", range(1, len(anchors) + 1))

    # Keep the committed table limited to public research-queue fields.
    ranking = anchors[[
        "rank", "ts_code", "name", "l1_name", "anchor_score",
        "dcf_base_margin_of_safety", "anchor_financial_check",
        "defensive_status", "moat_proxy_type",
    ]].rename(columns={
        "ts_code": "ticker",
        "l1_name": "industry",
        "anchor_score": "screen_score",
        "dcf_base_margin_of_safety": "base_dcf_margin",
        "anchor_financial_check": "financial_gate",
        "defensive_status": "screen_status",
        "moat_proxy_type": "moat_proxy_status",
    })
    docs_dir.mkdir(parents=True, exist_ok=True)
    ranking.to_csv(docs_dir / "public-screening-snapshot.csv", index=False, encoding="utf-8-sig")

    dcf_present = all_anchors["anchor_dcf_data_present"].astype(str).str.strip().str.lower().isin(
        {"true", "1", "yes"}
    )
    dcf_count = int(dcf_present.sum())
    nav_dates = nav["date"].astype(str).tolist() if "date" in nav else []
    status = {
        "snapshot_date": as_of,
        "securities_scanned": as_int(current["anchor_universe_scanned"]),
        "financial_reviewed": as_int(current["anchor_financial_reviewed"]),
        "financial_complete": as_int(current["anchor_financial_complete"]),
        "ranked_screen_rows": int(len(ranking)),
        "anchor_eligible": as_int(current["anchor_eligible"]),
        "dcf_valuations_generated": dcf_count,
        "moat_registry_records": int(len(registry)),
        "forward_nav_start_date": nav_dates[0] if nav_dates else "",
        "forward_nav_end_date": nav_dates[-1] if nav_dates else "",
        "radar_health_available": True,
        "radar_health_as_of": str(radar_health.iloc[0]["as_of_date"]) if not radar_health.empty else "",
        "screening_funnel": {
            "scanned": as_int(current["anchor_universe_scanned"]),
            "financial_reviewed_and_valuation_ready": as_int(current["anchor_financial_complete"]),
            "anchor_threshold": as_int(current["anchor_eligible"]),
            "public_research_queue": int(len(ranking)),
        },
        "source_files": [
            "outputs/barbell-strategy/portfolio_summary.csv",
            "outputs/barbell-strategy/anchor_screen.csv",
            "outputs/barbell-strategy/portfolio_nav_history.csv",
            "outputs/barbell-strategy/moat_radar_health.csv",
            "config/moat-thesis-registry.csv",
        ],
    }
    (docs_dir / "public-status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--docs-dir", type=Path, default=DEFAULT_DOCS)
    parser.add_argument("--ranking-rows", type=int, default=RANKING_ROWS)
    args = parser.parse_args()
    if args.ranking_rows < 5:
        parser.error("--ranking-rows must be at least 5")
    build_snapshot(args.output_dir, args.docs_dir, args.ranking_rows)
    print(f"wrote {args.docs_dir / 'public-status.json'}")
    print(f"wrote {args.docs_dir / 'public-screening-snapshot.csv'}")


if __name__ == "__main__":
    main()
