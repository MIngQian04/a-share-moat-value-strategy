# Allow running this file directly from the project root, e.g.
# python scripts/run_xxx.py
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import numpy as np
from pathlib import Path

VAL = Path("data/processed/selection/complement_valuation.csv")
DB = Path("data/processed/selection/complement_daily_basic.csv")

val = pd.read_csv(VAL)
db = pd.read_csv(DB)
db["trade_date"] = pd.to_datetime(db["trade_date"])

top_codes = val.sort_values("valuation_score", ascending=False).head(20)["ts_code"].tolist()

for code in top_codes:
    row = val[val["ts_code"] == code].iloc[0]
    g = db[db["ts_code"] == code].sort_values("trade_date")

    print("\n===", code, row.get("name", ""), row.get("industry", ""), "===")
    print("model:", row["valuation_model"])
    print("valuation_score:", row["valuation_score"])
    print("components:", row["valuation_components"])

    for col in ["pe_ttm", "pb", "dv_ttm"]:
        if col not in g.columns:
            continue
        x = pd.to_numeric(g[col], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
        if x.empty:
            continue
        latest = x.iloc[-1]
        pct = (x <= latest).mean() * 100
        print(
            col,
            "latest=", round(latest, 4),
            "p10=", round(x.quantile(0.10), 4),
            "p25=", round(x.quantile(0.25), 4),
            "median=", round(x.median(), 4),
            "p75=", round(x.quantile(0.75), 4),
            "pct=", round(pct, 2),
            "n=", len(x),
        )
