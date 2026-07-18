"""SW2021 industry-cycle map and conservative value-stock screen."""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
import time

import numpy as np
import pandas as pd

from data_loader.tushare_client import TushareClient
from industry.sw_cycle import INVESTABLE_STATES, industry_cycle_table
from valuation.owner_earnings import add_relative_valuation_scores, owner_earnings_from_statements


OUT = Path("outputs/sw-industry-value-screen")
META = Path("data/processed/metadata")
FIN = Path("data/raw/fundamental")
FINANCIAL_INDUSTRIES = {"银行", "非银金融"}


def load_sw2021(client: TushareClient, refresh: bool) -> tuple[pd.DataFrame, pd.DataFrame]:
    class_path, member_path = META / "sw2021_l1.csv", META / "sw2021_members.csv"
    if class_path.exists() and member_path.exists() and not refresh:
        return pd.read_csv(class_path), pd.read_csv(member_path)
    classes = client.pro.index_classify(level="L1", src="SW2021")
    member_parts = []
    for code in classes["index_code"].dropna().astype(str):
        part = client.pro.index_member_all(l1_code=code, is_new="Y")
        if part is not None and not part.empty:
            member_parts.append(part)
        time.sleep(client.sleep_seconds)
    members = pd.concat(member_parts, ignore_index=True) if member_parts else pd.DataFrame()
    if classes is None or classes.empty or members.empty:
        raise RuntimeError("Tushare returned empty SW2021 classification or membership")
    # Tushare currently returns l1_code/l1_name. Join from index_code when an
    # account exposes the older member schema.
    if "l1_name" not in members and "index_code" in members:
        lookup = classes.rename(columns={"industry_code": "index_code", "industry_name": "l1_name"})
        members = members.merge(lookup[["index_code", "l1_name"]], on="index_code", how="left")
    META.mkdir(parents=True, exist_ok=True)
    classes.to_csv(class_path, index=False, encoding="utf-8-sig")
    members = members.drop_duplicates("ts_code", keep="last")
    members.to_csv(member_path, index=False, encoding="utf-8-sig")
    return classes, members


def price_features(close: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for code in close.columns:
        s = pd.to_numeric(close[code], errors="coerce").dropna()
        if len(s) < 120:
            continue
        current, low, high = float(s.iloc[-1]), float(s.iloc[-min(252, len(s)):].min()), float(s.iloc[-min(252, len(s)):].max())
        position = (current - low) / (high - low) if high > low else 0.5
        ma20, ma60 = float(s.iloc[-20:].mean()), float(s.iloc[-60:].mean())
        rows.append({"ts_code": code, "price_position_252": position, "above_ma20": current >= ma20,
                     "above_ma60": current >= ma60, "return_20d": current / float(s.iloc[-21]) - 1})
    out = pd.DataFrame(rows)
    out["price_setup_score"] = 100 * (
        0.55 * (1 - out["price_position_252"].clip(0, 1))
        + 0.20 * out["above_ma20"].astype(float)
        + 0.15 * out["above_ma60"].astype(float)
        + 0.10 * out["return_20d"].clip(-0.2, 0.2).add(0.2).div(0.4)
    )
    return out


def fetch_statements(client: TushareClient, code: str, refresh: bool) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    result = []
    for endpoint in ["income", "cashflow", "balancesheet"]:
        path = FIN / endpoint / f"{code.replace('.', '_')}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and not refresh:
            df = pd.read_parquet(path)
        else:
            df = getattr(client.pro, endpoint)(ts_code=code, start_date="20190101")
            df = pd.DataFrame() if df is None else df
            df.to_parquet(path, index=False)
            time.sleep(client.sleep_seconds)
        result.append(df)
    return tuple(result)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="refresh SW membership and financial statements")
    parser.add_argument("--max-financials", type=int, default=40, help="number of preliminary candidates for statement valuation")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    client = TushareClient(data_dir="data/raw")
    _, members = load_sw2021(client, args.refresh)
    if not {"ts_code", "l1_name"}.issubset(members):
        raise ValueError(f"unexpected SW membership columns: {list(members.columns)}")
    close = pd.read_parquet("data/processed/research/close.parquet")
    cycle, industry_nav = industry_cycle_table(close, members)
    cycle.to_csv(OUT / "industry_cycle.csv", index=False, encoding="utf-8-sig")
    industry_nav.to_parquet(OUT / "industry_nav.parquet")

    daily = pd.read_csv("data/processed/portfolio/daily_basic_latest.csv")
    needed = {"pe_ttm", "ps_ttm", "total_share"}
    if not needed.issubset(daily):
        date = pd.Timestamp(close.index.max()).strftime("%Y%m%d")
        daily = client._cached_call(
            Path("data/processed/portfolio/daily_basic_latest.csv"), client.pro.daily_basic,
            overwrite=True, trade_date=date,
            fields="ts_code,trade_date,close,pe_ttm,pb,ps_ttm,dv_ratio,total_mv,total_share,float_share,free_share",
        )
    names = members[[c for c in ["ts_code", "name", "l1_name", "l2_name", "l3_name"] if c in members]].drop_duplicates("ts_code")
    screen = names.merge(daily, on="ts_code", how="inner").merge(cycle, on="l1_name", how="left").merge(price_features(close), on="ts_code", how="left")
    screen = screen[~screen.get("name", pd.Series("", index=screen.index)).astype(str).str.contains("ST|退", regex=True)]
    screen = add_relative_valuation_scores(screen)
    screen["preliminary_score"] = 0.35 * screen["cycle_score"] + 0.40 * screen["relative_value_score"] + 0.25 * screen["price_setup_score"]
    screen["industry_investable"] = screen["cycle_state"].isin(INVESTABLE_STATES)
    screen = screen.sort_values(["industry_investable", "preliminary_score"], ascending=[False, False])
    screen.to_csv(OUT / "preliminary_candidates.csv", index=False, encoding="utf-8-sig")

    researchable = screen["cycle_state"].isin(INVESTABLE_STATES | {"DEEP_BOTTOM"})
    candidates = (
        screen[researchable & ~screen["l1_name"].isin(FINANCIAL_INDUSTRIES)]
        .groupby("l1_name", as_index=False).head(3)
        .sort_values(["industry_investable", "preliminary_score"], ascending=[False, False])
        .head(args.max_financials)
    )
    financial_rows = []
    for _, row in candidates.iterrows():
        code = row["ts_code"]
        try:
            income, cashflow, balance = fetch_statements(client, code, args.refresh)
            total_shares = float(row["total_share"]) * 10000.0
            value = owner_earnings_from_statements(income, cashflow, balance, total_shares)
            market_cap = float(row["total_mv"]) * 10000.0
            owner_yield = value["normalized_owner_earnings"] / market_cap if market_cap > 0 else np.nan
            dcf_price = value["owner_earnings_value_per_share"]
            margin = dcf_price / float(row["close"]) - 1 if pd.notna(dcf_price) and row["close"] > 0 else np.nan
            for scenario in ["very_optimistic", "optimistic", "base", "cautious", "very_pessimistic"]:
                scenario_price = value.get(f"dcf_{scenario}_value_per_share")
                value[f"dcf_{scenario}_margin_of_safety"] = (
                    scenario_price / float(row["close"]) - 1
                    if pd.notna(scenario_price) and row["close"] > 0 else np.nan
                )
            financial_rows.append({"ts_code": code, **value, "owner_earnings_yield": owner_yield, "dcf_margin_of_safety": margin, "financial_error": ""})
        except Exception as exc:
            financial_rows.append({"ts_code": code, "financial_error": str(exc)[:200]})
    financial = pd.DataFrame(financial_rows)
    if financial.empty:
        financial = pd.DataFrame(columns=["ts_code"])
    valued = candidates.merge(financial, on="ts_code", how="left")
    valued["owner_yield_score"] = (pd.to_numeric(valued.get("owner_earnings_yield"), errors="coerce").clip(-0.05, 0.15) + 0.05) / 0.20 * 100
    valued["margin_safety_score"] = (pd.to_numeric(valued.get("dcf_margin_of_safety"), errors="coerce").clip(-0.5, 1.0) + 0.5) / 1.5 * 100
    valued["financial_value_score"] = 0.55 * valued["owner_yield_score"] + 0.45 * valued["margin_safety_score"]
    valued["final_research_score"] = 0.25 * valued["cycle_score"] + 0.25 * valued["relative_value_score"] + 0.20 * valued["price_setup_score"] + 0.30 * valued["financial_value_score"]
    passes_value = valued["normalized_owner_earnings"].gt(0) & valued["normalized_fcf"].gt(0) & valued["dcf_margin_of_safety"].gt(0)
    valued["research_status"] = np.select(
        [passes_value & valued["industry_investable"], passes_value & valued["cycle_state"].eq("DEEP_BOTTOM")],
        ["DEEP_REVIEW", "VALUATION_WATCH"], default="WATCH_OR_REJECT",
    )
    status_order = pd.Categorical(valued["research_status"], categories=["DEEP_REVIEW", "VALUATION_WATCH", "WATCH_OR_REJECT"], ordered=True)
    valued = valued.assign(_status_order=status_order).sort_values(["_status_order", "final_research_score"], ascending=[True, False]).drop(columns="_status_order")
    valued.to_csv(OUT / "valued_candidates.csv", index=False, encoding="utf-8-sig")
    print(cycle[["l1_name", "cycle_state", "cycle_score", "price_position_252"]].to_string(index=False))
    print("\nTop research candidates:")
    cols = ["ts_code", "name", "l1_name", "cycle_state", "close", "pb", "pe_ttm", "owner_earnings_value_per_share", "dcf_margin_of_safety", "final_research_score"]
    print(valued.loc[valued["research_status"].isin(["DEEP_REVIEW", "VALUATION_WATCH"]), [*cols, "research_status"]].head(20).round(3).to_string(index=False))
    print(f"\nSaved to {OUT}")


if __name__ == "__main__":
    main()
