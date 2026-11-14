"""
tests/test_sgb.py
Comprehensive unit tests for Sovereign Gold Bond (SGB) dynamic scraper and schema ingestion.
"""

import sqlite3
import unittest
from unittest.mock import MagicMock, patch

from modules.fixed_income.sgb_scraper import (
    MONTH_CODES,
    SGBScraper,
    parse_sgb_symbol_metadata,
)
from modules.fixed_income.sgb_collector import (
    init_sgb_schema,
    sync_sgb_tranches,
    _upsert_sgb_batch,
)


class TestSGBSymbolParsing(unittest.TestCase):
    def test_parse_sgb_symbol_standard(self):
        meta = parse_sgb_symbol_metadata("SGBFEB32IV")
        self.assertIsNotNone(meta)
        self.assertEqual(meta["symbol"], "SGBFEB32IV")
        self.assertEqual(meta["series"], "Series IV")
        self.assertEqual(meta["fiscal_year"], "2023-24")
        self.assertEqual(meta["name"], "SGB 2023-24 Series IV")
        self.assertEqual(meta["issue_date"], "2024-02-01")
        self.assertEqual(meta["maturity_date"], "2032-02-29")
        self.assertEqual(meta["coupon_rate"], 2.50)
        self.assertEqual(meta["coupon_months"], "2,8")
        self.assertEqual(meta["coupon_day"], 1)

    def test_parse_sgb_symbol_no_roman_numeral(self):
        meta = parse_sgb_symbol_metadata("SGBMAY28")
        self.assertIsNotNone(meta)
        self.assertEqual(meta["symbol"], "SGBMAY28")
        self.assertEqual(meta["series"], "Series I")
        self.assertEqual(meta["fiscal_year"], "2020-21")
        self.assertEqual(meta["name"], "SGB 2020-21 Series I")
        self.assertEqual(meta["issue_date"], "2020-05-01")
        self.assertEqual(meta["maturity_date"], "2028-05-31")
        self.assertEqual(meta["coupon_months"], "5,11")

    def test_parse_sgb_symbol_abbreviated_months(self):
        # D -> December, MR -> March, NV -> November, J -> January
        meta_d = parse_sgb_symbol_metadata("SGBD29VIII")
        self.assertIsNotNone(meta_d)
        self.assertEqual(meta_d["series"], "Series VIII")
        self.assertEqual(meta_d["coupon_months"], "6,12")

        meta_mr = parse_sgb_symbol_metadata("SGBMR29XII")
        self.assertIsNotNone(meta_mr)
        self.assertEqual(meta_mr["series"], "Series XII")

        meta_j = parse_sgb_symbol_metadata("SGBJ28VIII")
        self.assertIsNotNone(meta_j)
        self.assertEqual(meta_j["series"], "Series VIII")
        self.assertEqual(meta_j["coupon_months"], "1,7")

    def test_parse_invalid_symbol(self):
        self.assertIsNone(parse_sgb_symbol_metadata("NOT_AN_SGB"))
        self.assertIsNone(parse_sgb_symbol_metadata(""))
        self.assertIsNone(parse_sgb_symbol_metadata("SGBZZ99"))


class TestSGBDatabaseIngestion(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")

    def tearDown(self):
        self.conn.close()

    def test_init_sgb_schema_creates_table_and_indices(self):
        init_sgb_schema(self.conn)
        cursor = self.conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='master_sgb_tranches'")
        self.assertIsNotNone(cursor.fetchone())

        cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='master_sgb_tranches'")
        indices = {row[0] for row in cursor.fetchall()}
        self.assertIn("idx_sgb_symbol", indices)
        self.assertIn("idx_sgb_name", indices)
        self.assertIn("idx_sgb_series", indices)
        self.assertIn("idx_sgb_status", indices)

    def test_upsert_sgb_batch_and_conflict_handling(self):
        init_sgb_schema(self.conn)
        batch = [
            (
                "SGB_SGBFEB32IV",
                "SGBFEB32IV",
                "SGB 2023-24 Series IV",
                "Series IV",
                "2024-02-01",
                "2032-02-29",
                6213.0,
                2.50,
                "2,8",
                1,
                14500.0,
                "2026-11-14",
                "ACTIVE",
                "2026-11-14T00:00:00Z",
            )
        ]
        _upsert_sgb_batch(self.conn, batch)

        cursor = self.conn.cursor()
        cursor.execute("SELECT symbol, issue_price, latest_price FROM master_sgb_tranches WHERE uid='SGB_SGBFEB32IV'")
        row = cursor.fetchone()
        self.assertEqual(row, ("SGBFEB32IV", 6213.0, 14500.0))

        # Update latest_price
        batch_update = [
            (
                "SGB_SGBFEB32IV",
                "SGBFEB32IV",
                "SGB 2023-24 Series IV",
                "Series IV",
                "2024-02-01",
                "2032-02-29",
                6213.0,
                2.50,
                "2,8",
                1,
                14650.0,
                "2026-11-14",
                "ACTIVE",
                "2026-11-14T10:00:00Z",
            )
        ]
        _upsert_sgb_batch(self.conn, batch_update)
        cursor.execute("SELECT latest_price FROM master_sgb_tranches WHERE uid='SGB_SGBFEB32IV'")
        self.assertEqual(cursor.fetchone()[0], 14650.0)


if __name__ == "__main__":
    unittest.main()
