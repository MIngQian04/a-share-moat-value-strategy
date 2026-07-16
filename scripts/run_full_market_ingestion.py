# Allow running this file directly from the project root, e.g.
# python scripts/run_xxx.py
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import yaml
from data_loader.tushare_client import TushareClient
from data_loader.full_market import FullMarketIngestor

if __name__ == "__main__":
    with open("config/config.yaml", "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    client = TushareClient(data_dir="data/raw")
    ingestor = FullMarketIngestor(
        client,
        output_dir="data/raw/market_daily",
        sleep_seconds=cfg["full_market"]["sleep_seconds"],
    )
    result = ingestor.ingest(
        cfg["data"]["start_date"],
        cfg["data"]["end_date"],
        overwrite=cfg["cache"]["overwrite"],
    )
    print(f"downloaded={result['downloaded']} cached={result['cached']} failed={len(result['failed'])}")
    if result["failed"]:
        print("First failures:", result["failed"][:10])
