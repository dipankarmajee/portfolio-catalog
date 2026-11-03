"""
tests/test_ulips.py
Unit tests for ULIP SFIN statutory date parsing, insurer matching, and schema setup.
"""

import sqlite3
import unittest

from modules.ulips.ulip_collector import extract_inception_date_from_sfin, init_ulips_schema, match_insurer_id


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

    def test_sfin_inception_date_extraction(self):
        # Format: ULIF009310505... -> 31-05-2005
        date_str = extract_inception_date_from_sfin("ULIF009310505BALICGRFND111")
        self.assertEqual(date_str, "2005-05-31")

        # Format: ULIF001150108... -> 15-01-2008
        date_str2 = extract_inception_date_from_sfin("ULIF001150108PRUOPPFUND111")
        self.assertEqual(date_str2, "2008-01-15")

        # Invalid returns None
        self.assertIsNone(extract_inception_date_from_sfin("INVALID_SFIN"))
        self.assertIsNone(extract_inception_date_from_sfin(None))

    def test_insurer_id_fuzzy_matching(self):
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

