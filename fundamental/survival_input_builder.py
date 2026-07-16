from __future__ import annotations

from pathlib import Path
import pandas as pd

from fundamental.point_in_time import FinancialPointInTimeStore


def first_available(row, names: list[str]):
    if row is None:
        return None

    for name in names:
        if name in row.index and pd.notna(row[name]):
            return row[name]

    return None


class SurvivalInputBuilder:
    """
    Build data/processed/fundamental/survival_input.csv

    This file feeds SurvivalAssetCapacityEngine.

    Important:
        It uses point-in-time latest available statements:
            ann_date <= decision_date
    """

    def __init__(
        self,
        store: FinancialPointInTimeStore,
        output_dir: str | Path = "data/processed/fundamental",
    ):
        self.store = store
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def build_for_candidates(
        self,
        candidates: pd.DataFrame,
        decision_date: str,
    ) -> pd.DataFrame:
        rows = []

        for _, candidate in candidates.iterrows():
            ts_code = str(candidate["ts_code"])
            theme = str(candidate["theme"])

            bundle = self.store.latest_statement_bundle(
                ts_code=ts_code,
                decision_date=decision_date,
            )

            bs = bundle.get("balancesheet")
            bs_prev = bundle.get("balancesheet_prev")
            inc = bundle.get("income")
            inc_prev = bundle.get("income_prev")
            cf = bundle.get("cashflow")
            fi = bundle.get("fina_indicator")

            current_end_date = (
                first_available(bs, ["end_date"])
                or first_available(inc, ["end_date"])
                or first_available(cf, ["end_date"])
            )

            row = {
                "theme": theme,
                "ts_code": ts_code,
                "decision_date": decision_date,
                "financial_end_date": current_end_date,
                "financial_ann_date": (
                    first_available(bs, ["ann_date"])
                    or first_available(inc, ["ann_date"])
                    or first_available(cf, ["ann_date"])
                ),
            }

            # Balance sheet fields.
            row["cash"] = first_available(
                bs,
                [
                    "money_cap",
                    "cash_equ_end_period",
                ],
            )

            row["short_debt"] = first_available(
                bs,
                [
                    "st_borr",
                    "short_borr",
                ],
            )

            row["total_debt"] = first_available(
                bs,
                [
                    "total_liab",
                    "total_cur_liab",
                ],
            )

            row["total_assets"] = first_available(bs, ["total_assets"])
            row["total_assets_prev"] = first_available(bs_prev, ["total_assets"])

            row["fixed_assets"] = first_available(
                bs,
                [
                    "fix_assets",
                    "fixed_assets",
                ],
            )
            row["fixed_assets_prev"] = first_available(
                bs_prev,
                [
                    "fix_assets",
                    "fixed_assets",
                ],
            )

            row["construction_in_progress"] = first_available(
                bs,
                [
                    "cip",
                    "const_in_prog",
                    "constru_in_process",
                ],
            )
            row["construction_in_progress_prev"] = first_available(
                bs_prev,
                [
                    "cip",
                    "const_in_prog",
                    "constru_in_process",
                ],
            )

            # Income fields.
            row["revenue"] = first_available(
                inc,
                [
                    "revenue",
                    "total_revenue",
                ],
            )
            row["revenue_prev"] = first_available(
                inc_prev,
                [
                    "revenue",
                    "total_revenue",
                ],
            )

            row["ebit"] = first_available(
                inc,
                [
                    "ebit",
                    "operate_profit",
                    "total_profit",
                ],
            )

            row["interest_expense"] = first_available(
                inc,
                [
                    "int_exp",
                    "fin_exp",
                    "interest_exp",
                ],
            )

            # Cash flow fields.
            row["operating_cash_flow"] = first_available(
                cf,
                [
                    "n_cashflow_act",
                    "net_cash_flows_oper_act",
                    "net_cash_flows_from_operating_activities",
                ],
            )

            # IMPORTANT FIX:
            # Do NOT use c_disp_withdrwl_invest here.
            # c_disp_withdrwl_invest means cash received from withdrawing investments,
            # not disposal of productive assets.
            #
            # Correct concept:
            # cash received from disposal of fixed assets, intangible assets,
            # and other long-term assets.
            row["cash_from_asset_disposals"] = first_available(
                cf,
                [
                    "c_recp_disp_fiolta",
                    "c_disp_fiolta",
                    "c_recp_disp_fixed_assets",
                ],
            )

            # CAPEX proxy:
            # cash paid to acquire / construct fixed assets, intangible assets,
            # and other long-term assets.
            row["capex_cash_paid"] = first_available(
                cf,
                [
                    "c_pay_acq_const_fiolta",
                    "c_pay_acq_const_fa_intan",
                    "cash_pay_acq_const_fiolta",
                ],
            )

            # Supplementary fields if fina_indicator has them.
            row["debt_to_assets"] = first_available(
                fi,
                [
                    "debt_to_assets",
                    "assets_to_liab",
                ],
            )

            row["ocf_to_or"] = first_available(
                fi,
                [
                    "ocf_to_or",
                    "ocf_to_revenue",
                ],
            )

            rows.append(row)

        out = pd.DataFrame(rows)

        out_path = self.output_dir / "survival_input.csv"
        out.to_csv(out_path, index=False, encoding="utf-8-sig")

        return out
