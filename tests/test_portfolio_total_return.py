from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

import portfolio.site_export as site_export


def test_cash_and_stock_dividends_offset_ex_date_price_drop_and_reinvest_next_session():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        output = root / "out"
        output.mkdir()
        dividend_path = root / "dividend_events.csv"
        old_path = site_export.DIVIDEND_EVENTS_PATH
        site_export.DIVIDEND_EVENTS_PATH = dividend_path
        try:
            pd.DataFrame([{
                "ts_code": "A", "end_date": "2025-12-31", "ex_date": "2026-07-16",
                "pay_date": "2026-07-16", "cash_div": 2.0, "stk_div": 0.1,
            }]).to_csv(dividend_path, index=False)
            pd.DataFrame([{
                "ts_code": "A", "name": "A", "allocation_bucket": "ANCHOR",
                "target_weight": 0.5,
            }]).to_csv(output / "target_portfolio.csv", index=False)
            pd.DataFrame([{"as_of_date": "2026-07-16"}]).to_csv(output / "portfolio_summary.csv", index=False)
            pd.DataFrame([{
                "date": "2026-07-15", "ts_code": "A", "name": "A",
                "allocation_bucket": "ANCHOR", "target_weight": 0.5, "close": 100.0,
            }]).to_csv(output / "portfolio_holdings_history.csv", index=False)
            pd.DataFrame([{
                "date": "2026-07-15", "nav": 1.0, "daily_return": 0.0, "price_coverage": 0.5,
            }]).to_csv(output / "portfolio_nav_history.csv", index=False)

            daily = pd.DataFrame([{"ts_code": "A", "close": 90.0}])
            site_export.update_portfolio_nav_history(output, daily)
            nav = pd.read_csv(output / "portfolio_nav_history.csv").iloc[-1]
            assert abs(nav["price_return"] + 0.05) < 1e-12
            assert abs(nav["cash_dividend_return"] - 0.01) < 1e-12
            assert abs(nav["stock_dividend_return"] - 0.045) < 1e-12
            assert abs(nav["nav"] - 1.005) < 1e-12
            assert abs(nav["pending_dividend_cash"] - 0.01) < 1e-12

            pd.DataFrame([{"as_of_date": "2026-07-17"}]).to_csv(output / "portfolio_summary.csv", index=False)
            site_export.update_portfolio_nav_history(output, daily)
            nav = pd.read_csv(output / "portfolio_nav_history.csv").iloc[-1]
            assert abs(nav["reinvested_dividend_cash"] - 0.01) < 1e-12
            assert abs(nav["pending_dividend_cash"]) < 1e-12
        finally:
            site_export.DIVIDEND_EVENTS_PATH = old_path
