#!/usr/bin/env python3
"""Generate the Aiko fundamental/industry/price monitoring report."""
from __future__ import annotations
import sys
import argparse
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from data_loader.tushare_client import TushareClient
from research.aiko_monitor import PEERS, _read_ledger, make_report, market_snapshot

START, DEFAULT_END, CODE = "20180101", "20260710", "600732.SH"
def main():
    parser=argparse.ArgumentParser(description="Generate the Aiko monitoring report")
    parser.add_argument("--start-date",default=START)
    parser.add_argument("--end-date",default=DEFAULT_END)
    parser.add_argument("--report-date",default="20260713",help="Include ledger facts public by this date")
    args=parser.parse_args()
    c=TushareClient(data_dir=ROOT/"data/raw")
    stock=c.stock_daily(CODE,args.start_date,args.end_date); basic=c.daily_basic(CODE,args.start_date,args.end_date); flow=c.moneyflow(CODE,args.start_date,args.end_date)
    peers=pd.concat({x:c.stock_daily(x,args.start_date,args.end_date).close for x in PEERS},axis=1,sort=True)
    income=c.income(CODE,args.start_date,args.end_date)
    snapshot=market_snapshot(stock,basic,flow,peers)
    report_date=pd.to_datetime(args.report_date,format="%Y%m%d")
    kpis=_read_ledger(ROOT/"config/aiko_operating_kpis.csv",report_date,"announcement_date")
    industry=_read_ledger(ROOT/"config/aiko_industry_weekly.csv",report_date,"release_date")
    out=ROOT/"outputs/aiko-monitor"; out.mkdir(parents=True,exist_ok=True)
    (out/"README.md").write_text(make_report(snapshot,kpis,industry,income),encoding="utf-8")
    pd.DataFrame([snapshot]).to_csv(out/"market_snapshot.csv",index=False)
    print((out/"README.md").read_text())
if __name__ == "__main__": main()
