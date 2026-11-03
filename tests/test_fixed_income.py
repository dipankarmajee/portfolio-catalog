"""
tests/test_fixed_income.py
Unit tests for Fixed Income dynamic scraping logic and schema setup.
"""

import sqlite3
import unittest
from unittest.mock import MagicMock, patch

from modules.fixed_income.fixed_income_collector import init_fixed_income_schema, sync_fixed_income
from modules.fixed_income.nsi_scraper import NSIScraper
from modules.fixed_income.rbi_scraper import RBIScraper
from modules.fixed_income.us_treasury_scraper import USTreasuryScraper


class TestFixedIncome(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")

    def tearDown(self):
        self.conn.close()

    def test_init_schema(self):
        init_fixed_income_schema(self.conn)
        cursor = self.conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='master_fixed_income'")
        self.assertIsNotNone(cursor.fetchone())

    def test_nsi_scraper_mapping(self):
        from modules.fixed_income.nsi_scraper import SCHEME_PATTERNS
        codes = [item[0] for item in SCHEME_PATTERNS]
        self.assertIn("PPF", codes)
        self.assertIn("SSY", codes)
        self.assertIn("SCSS", codes)

    def test_sync_fixed_income_mocked(self):
        with patch.object(NSIScraper, "scrape_schemes_rates", return_value=[{
            "uid": "FI_PPF", "scheme_code": "PPF", "scheme_name": "Public Provident Fund",
            "issuer": "Ministry of Finance", "category": "SMALL_SAVINGS", "country": "IND",
            "currency": "INR", "interest_rate_percent": 7.10, "senior_citizen_rate_percent": 7.10,
            "compounding_frequency": "ANNUAL", "payout_frequency": "AT_MATURITY",
            "min_tenure_months": 180, "max_tenure_months": 0, "min_deposit": 500.0,
            "max_deposit": 150000.0, "tax_treatment": "EEE", "tax_section": "80C",
            "effective_from": "2026-04-01", "formula_notes": "Statutory rule",
            "status": "ACTIVE", "updated_at": "2026-11-04 00:00:00Z"
        }]), patch.object(USTreasuryScraper, "fetch_latest_yields", return_value=[]), \
             patch.object(RBIScraper, "fetch_policy_rates", return_value=[]):

            count = sync_fixed_income(self.conn)
            self.assertEqual(count, 1)

            cursor = self.conn.cursor()
            cursor.execute("SELECT scheme_name, interest_rate_percent, tax_treatment FROM master_fixed_income WHERE scheme_code='PPF'")
            row = cursor.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], "Public Provident Fund")
            self.assertEqual(row[1], 7.10)
            self.assertEqual(row[2], "EEE")


if __name__ == "__main__":
    unittest.main()
