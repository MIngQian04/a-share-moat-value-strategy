import pandas as pd
from data_loader.universe import build_a_share_universe

def test_build_universe_filters_prefix_and_list_days():
    stock_basic = pd.DataFrame({
        "ts_code": ["600000.SH", "830000.BJ", "000001.SZ"],
        "symbol": ["600000", "830000", "000001"],
        "name": ["A", "B", "C"],
        "industry": ["Bank", "BSE", "Bank"],
        "list_date": pd.to_datetime(["2000-01-01", "2000-01-01", "2025-01-01"]),
    })
    out = build_a_share_universe(stock_basic, "2026-07-03", min_list_days=800)
    assert out["ts_code"].tolist() == ["600000.SH"]
