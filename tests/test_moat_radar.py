import tempfile
import unittest
from pathlib import Path

import pandas as pd

from selection.moat_radar import build_announcement_alerts, build_financial_alerts


class MoatRadarTests(unittest.TestCase):
    def test_keyword_creates_review_candidate_not_moat_verdict(self):
        announcements = pd.DataFrame([{
            "ann_date": "2026-07-15", "ts_code": "600000.SH", "name": "样本",
            "title": "关于收到行政处罚决定书的公告", "url": "https://example.com/a.pdf",
        }])
        alerts = build_announcement_alerts(announcements, "2026-07-15")
        self.assertEqual(alerts.iloc[0]["alert_level"], "HIGH")
        self.assertEqual(alerts.iloc[0]["review_status"], "PENDING_REVIEW")
        self.assertNotIn("WEAKENED", alerts.to_string())

    def test_benign_announcement_does_not_trigger(self):
        announcements = pd.DataFrame([{
            "ann_date": "2026-07-15", "ts_code": "600000.SH", "name": "样本",
            "title": "2025年度权益分派实施公告", "url": "https://example.com/a.pdf",
        }])
        self.assertTrue(build_announcement_alerts(announcements, "2026-07-15").empty)

    def test_same_period_financial_decline_only_triggers_review(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "income").mkdir()
            (root / "cashflow").mkdir()
            pd.DataFrame([
                {"ann_date": "20260430", "end_date": "20260331", "revenue": 80, "n_income_attr_p": 70},
                {"ann_date": "20250430", "end_date": "20250331", "revenue": 100, "n_income_attr_p": 100},
            ]).to_parquet(root / "income/600000_SH.parquet")
            pd.DataFrame([
                {"ann_date": "20260430", "end_date": "20260331", "n_cashflow_act": 60},
                {"ann_date": "20250430", "end_date": "20250331", "n_cashflow_act": 100},
            ]).to_parquet(root / "cashflow/600000_SH.parquet")
            alerts, health = build_financial_alerts(
                pd.DataFrame([{"ts_code": "600000.SH", "name": "样本"}]), root, "2026-07-15"
            )
        self.assertEqual(health["codes_checked"], 1)
        self.assertEqual(set(alerts["trigger"]), {"收入同比", "归母净利润同比", "经营现金流同比"})
        self.assertTrue(alerts["review_status"].eq("PENDING_REVIEW").all())


if __name__ == "__main__":
    unittest.main()
