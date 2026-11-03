"""
tests/test_ulips.py
Unit tests for ULIP SFIN statutory date parsing, insurer matching,
asset categorization, fund typing, and schema setup.
"""

import sqlite3
import unittest

from modules.ulips.ulip_collector import (
    classify_ulip_fund,
    extract_inception_date_from_sfin,
    format_ulip_search_name,
    init_ulips_schema,
    match_insurer_id,
)


class TestUlips(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")

    def tearDown(self):
        self.conn.close()

    def test_schema_init(self):
        init_ulips_schema(self.conn)
        cursor = self.conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='master_ulip_funds'")
        self.assertIsNotNone(cursor.fetchone())
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='master_insurers'")
        self.assertIsNotNone(cursor.fetchone())

        # Verify new schema columns
        cursor.execute("PRAGMA table_info(master_ulip_funds)")
        cols = {row[1] for row in cursor.fetchall()}
        self.assertIn("name", cols)
        self.assertIn("fund_name", cols)
        self.assertIn("insurer_name", cols)
        self.assertIn("category", cols)
        self.assertIn("fund_type", cols)
        self.assertNotIn("commercial_product_name", cols)
        self.assertNotIn("statutory_uin", cols)

    def test_sfin_inception_date_extraction(self):
        # Format: ULIF009310505... -> 31-05-2005
        date_str = extract_inception_date_from_sfin("ULIF009310505BALICGRFND111")
        self.assertEqual(date_str, "2005-05-31")

        # Format: ULIF001150108... -> 15-01-2008
        date_str2 = extract_inception_date_from_sfin("ULIF001150108PRUOPPFUND111")
        self.assertEqual(date_str2, "2008-01-15")

        # Group fund format: ULGF017281111... -> 28-11-2011
        date_str3 = extract_inception_date_from_sfin("ULGF017281111BSLGFXINT2109")
        self.assertEqual(date_str3, "2011-11-28")

        # Hyphenated format: ULIF-009-270603... -> 27-06-2003
        date_str4 = extract_inception_date_from_sfin("ULIF-009-270603-DYBALFND-107")
        self.assertEqual(date_str4, "2003-06-27")

        # Invalid returns None
        self.assertIsNone(extract_inception_date_from_sfin("INVALID_SFIN"))
        self.assertIsNone(extract_inception_date_from_sfin(None))

    def test_classify_ulip_fund(self):
        # 1. Equity fund
        cat, ftype = classify_ulip_fund("ULIF001040108EQTYPLUSFD111", "SBI Life - Equity Plus Fund")
        self.assertEqual(cat, "EQUITY")
        self.assertEqual(ftype, "INDIVIDUAL")

        # 2. Debt fund
        cat, ftype = classify_ulip_fund("ULIF002040108BONDPLSFND111", "SBI Life - Bond Plus Fund")
        self.assertEqual(cat, "DEBT")
        self.assertEqual(ftype, "INDIVIDUAL")

        # 3. Balanced / Hybrid fund
        cat, ftype = classify_ulip_fund("ULIF003040108BALANCPFND111", "SBI Life - Balanced Fund")
        self.assertEqual(cat, "BALANCED")
        self.assertEqual(ftype, "INDIVIDUAL")

        # 4. Pension fund
        cat, ftype = classify_ulip_fund("ULIF004040108PENSNPLSFD111", "SBI Life - Pension Plus Fund")
        self.assertEqual(cat, "PENSION")
        self.assertEqual(ftype, "INDIVIDUAL")

        # 5. Money Market / Liquid fund
        cat, ftype = classify_ulip_fund("ULIF005040108MNYMKTPLUS111", "SBI Life - Money Market Plus Fund")
        self.assertEqual(cat, "MONEY_MARKET")
        self.assertEqual(ftype, "INDIVIDUAL")

        # 6. Group fund
        cat, ftype = classify_ulip_fund("ULGF002100806GRPOPTIGRO111", "SBI Life - Group Growth Fund")
        self.assertEqual(cat, "EQUITY")
        self.assertEqual(ftype, "GROUP")

        # 7. Discontinued Policy fund
        cat, ftype = classify_ulip_fund("DPFF001010111DISCONTFND111", "SBI Life - Discontinued Policy Fund")
        self.assertEqual(cat, "DISCONTINUED")
        self.assertEqual(ftype, "DISCONTINUED")

    def test_format_ulip_search_name(self):
        # Prefixes brand name cleanly
        name1 = format_ulip_search_name("SBI Life Insurance Company Limited", "EQUITY FUND")
        self.assertEqual(name1, "SBI Life - Equity Fund")

        # Does not duplicate if already prefixed
        name2 = format_ulip_search_name("SBI Life Insurance Company Limited", "SBI Life - Smart Wealth Builder")
        self.assertEqual(name2, "SBI Life - Smart Wealth Builder")

        # Handles LIC special case
        name3 = format_ulip_search_name("Life Insurance Corporation of India", "Bond Fund")
        self.assertEqual(name3, "LIC - Bond Fund")

    def test_insurer_id_deterministic_matching(self):
        registry = {
            "hdfc": "INS_101",
            "icici prudential": "INS_105",
            "sbi": "INS_111",
            "lic": "INS_512"
        }
        self.assertEqual(match_insurer_id("HDFC Life Insurance Co Ltd", registry), "INS_101")
        self.assertEqual(match_insurer_id("ICICI Prudential Life Insurance", registry), "INS_105")
        self.assertEqual(match_insurer_id("Life Insurance Corporation of India", registry), "INS_512")


if __name__ == "__main__":
    unittest.main()
