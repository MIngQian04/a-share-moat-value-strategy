# Allow running this file directly from the project root, e.g.
# python scripts/run_xxx.py
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_loader.market_store import MarketStore
from research.dataset_builder import ResearchDatasetBuilder

if __name__ == "__main__":
    store = MarketStore("data/raw/market_daily")
    builder = ResearchDatasetBuilder(store)
    data = builder.build()
    print("close:", data["close"].shape)
    print("returns:", data["returns"].shape)
    print("tradable ratio:", float(data["tradable_mask"].mean().mean()))
