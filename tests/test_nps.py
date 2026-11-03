"""
tests/test_nps.py
Unit tests for National Pension System (NPS) classification and schema setup.
"""

import sqlite3
import unittest
from unittest.mock import patch

from modules.nps.nps_collector import _detect_asset_class, _detect_tier, init_nps_schema, sync_nps


class TestNPSCollector(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")

    def tearDown(self):
        self.conn.close()

    def test_tier_detection(self):
        self.assertEqual(_detect_tier("SBI PENSION FUND SCHEME E - TIER I"), "TIER_I")
        self.assertEqual(_detect_tier("HDFC PENSION FUND SCHEME C - TIER II"), "TIER_II")
        self.assertEqual(_detect_tier("LIC PENSION FUND SCHEME - CENTRAL GOVT"), "GOVERNMENT")
        self.assertEqual(_detect_tier("ICICI PENSION FUND - CORPORATE"), "CORPORATE")

    def test_asset_class_detection(self):
        self.assertEqual(_detect_asset_class("SBI PENSION FUND SCHEME E - TIER I"), "E")
        self.assertEqual(_detect_asset_class("UTI RETIREMENT SOLUTIONS SCHEME C"), "C")
        self.assertEqual(_detect_asset_class("KOTAK PENSION FUND SCHEME G"), "G")
        self.assertEqual(_detect_asset_class("MAX LIFE PENSION FUND SCHEME A"), "A")

    def test_schema_init(self):
        init_nps_schema(self.conn)
        cursor = self.conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='master_nps'")
        self.assertIsNotNone(cursor.fetchone())

    def test_sync_nps_mocked(self):
        sample_data = [{
            "uid": "NPS_SM001001",
            "scheme_code": "SM001001",
            "scheme_name": "SBI PENSION FUND SCHEME - CENTRAL GOVT",
            "pfm_name": "SBI Pension Funds Pvt. Ltd.",
            "tier": "GOVERNMENT",
            "asset_class": "ALL",
            "country": "IND",
            "currency": "INR",
            "latest_nav": 49.9615,
            "nav_date": "2026-11-02",
            "return_1y": 0.62,
            "return_3y": 6.86,
            "return_5y": 6.14,
            "tax_section": None,
            "status": "ACTIVE",
            "updated_at": "2026-11-04 00:00:00Z"
        }]
        with patch("modules.nps.nps_collector.fetch_nps_schemes", return_value=sample_data):
            count = sync_nps(self.conn)
            self.assertEqual(count, 1)

            cursor = self.conn.cursor()
            cursor.execute("SELECT scheme_name, latest_nav FROM master_nps WHERE scheme_code='SM001001'")
            row = cursor.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[1], 49.9615)


if __name__ == "__main__":
    unittest.main()

