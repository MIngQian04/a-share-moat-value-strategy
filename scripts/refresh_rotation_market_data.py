"""Extend the cached market matrices through the latest completed SSE session."""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
import time

import pandas as pd

from data_loader.tushare_client import TushareClient
from data_loader.dividend_store import refresh_dividend_events


def latest_open_date(pro, as_of: str) -> str:
    cal = pro.trade_cal(exchange="SSE", start_date="20260101", end_date=as_of, is_open="1", fields="cal_date,is_open")
    if cal is None or cal.empty:
        raise RuntimeError("Tushare returned no open trading date")
    return str(cal["cal_date"].astype(str).max())


def append_market_days(matrix: pd.DataFrame, daily_frames: list[pd.DataFrame], field: str) -> pd.DataFrame:
    """Append requested field for existing universe only, retaining chronological order."""
    rows = []
    universe = matrix.columns
    for daily in daily_frames:
        if daily is None or daily.empty or field not in daily.columns:
            continue
        date = pd.to_datetime(str(daily["trade_date"].iloc[0]))
        values = daily.set_index("ts_code")[field].reindex(universe)
        rows.append(pd.DataFrame([values.values], index=[date], columns=universe))
    if not rows:
        return matrix
    return pd.concat([matrix, *rows]).loc[lambda x: ~x.index.duplicated(keep="last")].sort_index()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", default=pd.Timestamp.today().strftime("%Y%m%d"), help="calendar date, YYYYMMDD")
    args = parser.parse_args()
    close_path = Path("data/processed/research/close.parquet")
    volume_path = Path("data/processed/research/volume.parquet")
    close, volume = pd.read_parquet(close_path), pd.read_parquet(volume_path)
    client = TushareClient(data_dir="data/raw")
    end_date = latest_open_date(client.pro, args.as_of)
    start_date = (pd.Timestamp(close.index.max()) + pd.Timedelta(days=1)).strftime("%Y%m%d")
    calendar = client.pro.trade_cal(exchange="SSE", start_date=start_date, end_date=end_date, is_open="1", fields="cal_date,is_open")
    dates = [] if calendar is None else sorted(calendar["cal_date"].astype(str).tolist())
    frames = []
    for date in dates:
        daily = client.pro.daily(trade_date=date)
        if daily is None or daily.empty:
            # The exchange calendar can mark today open before the end-of-day
            # dataset is published. Keep completed sessions and fall back to
            # the last one instead of failing the whole refresh.
            if date == dates[-1]:
                print(f"skip_unpublished_session={date}")
                break
            raise RuntimeError(f"empty daily response for {date}")
        frames.append(daily)
        time.sleep(client.sleep_seconds)
    if frames:
        end_date = str(frames[-1]["trade_date"].iloc[0])
    else:
        end_date = pd.Timestamp(close.index.max()).strftime("%Y%m%d")
    close = append_market_days(close, frames, "close")
    volume = append_market_days(volume, frames, "vol")
    close.to_parquet(close_path)
    volume.to_parquet(volume_path)

    basic = client._cached_call(
        Path("data/processed/portfolio/daily_basic_latest.csv"), client.pro.daily_basic,
        overwrite=True, trade_date=end_date,
        fields="ts_code,trade_date,close,pe_ttm,pb,ps_ttm,dv_ratio,total_mv,total_share,float_share,free_share",
    )
    held_codes: set[str] = set()
    for source in [
        Path("outputs/barbell-strategy/portfolio_holdings_history.csv"),
        Path("outputs/barbell-strategy/target_portfolio.csv"),
    ]:
        if source.exists():
            held = pd.read_csv(source, usecols=["ts_code"])
            held_codes.update(held["ts_code"].dropna().astype(str))
    dividends, dividend_errors = refresh_dividend_events(
        client.pro,
        sorted(held_codes),
        Path("data/processed/portfolio/dividend_events.csv"),
        sleep_seconds=client.sleep_seconds,
    )
    print(f"latest_open_date={end_date} appended_days={len(frames)} close_rows={len(close)} daily_basic_rows={len(basic)}")
    print(f"dividend_events={len(dividends)} dividend_fetch_errors={len(dividend_errors)}")
    if dividend_errors:
        print("dividend_fetch_warning=" + ",".join(dividend_errors))


if __name__ == "__main__":
    main()
