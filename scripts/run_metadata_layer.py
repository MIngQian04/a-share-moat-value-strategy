# Allow running this file directly from the project root, e.g.
# python scripts/run_xxx.py
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_loader.tushare_client import TushareClient
from metadata.security_master import SecurityMasterBuilder

if __name__ == "__main__":
    client = TushareClient(data_dir="data/raw")
    builder = SecurityMasterBuilder(client)

    master = builder.build_security_master()
    namechange = builder.build_namechange_history(master)

    print("security_master:", master.shape)
    print("namechange_history:", namechange.shape)

    for d in ["2019-06-30", "2022-06-30", "2026-06-30"]:
        u = builder.build_point_in_time_universe(
            master,
            d,
            exclude_st=True,
            namechange=namechange,
            min_list_days=180,
        )
        print(f"universe({d}): {len(u)}")
