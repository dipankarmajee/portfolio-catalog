"""
tests/test_commodities_crypto.py
Unit tests for Commodities and Crypto collectors schema setup and data handling.
"""

import sqlite3
import unittest
from unittest.mock import patch

from modules.commodities.ibja_collector import init_commodities_schema, sync_commodities
from modules.crypto.crypto_collector import init_crypto_schema, sync_crypto


class TestCommoditiesAndCrypto(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")

    def tearDown(self):
        self.conn.close()

    def test_commodities_schema(self):
        init_commodities_schema(self.conn)
        cursor = self.conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='master_commodities'")
        self.assertIsNotNone(cursor.fetchone())

    def test_crypto_schema(self):
        init_crypto_schema(self.conn)
        cursor = self.conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='master_crypto'")
        self.assertIsNotNone(cursor.fetchone())

    def test_sync_commodities_mocked(self):
        sample_rates = [{
            "uid": "COMMODITY_GOLD_999_10G",
            "symbol": "GOLD_999_10G",
            "name": "Gold 24K (999 Purity) - 10g",
            "commodity_type": "GOLD",
            "purity": "999 (24K)",
            "unit": "10_GRAMS",
            "country": "IND",
            "currency": "INR",
            "rate": 137576.0,
            "rate_date": "2026-11-04",
            "high_all_time": 137576.0,
            "low_all_time": 137576.0,
            "source": "IBJA",
            "status": "ACTIVE",
            "updated_at": "2026-11-04 00:00:00Z"
        }]
        with patch("modules.commodities.ibja_collector.fetch_ibja_rates", return_value=sample_rates):
            count = sync_commodities(self.conn)
            self.assertEqual(count, 1)

            cursor = self.conn.cursor()
            cursor.execute("SELECT rate FROM master_commodities WHERE symbol='GOLD_999_10G'")
            row = cursor.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], 137576.0)

    def test_sync_crypto_mocked(self):
        sample_crypto = [{
            "uid": "CRYPTO_BTC",
            "symbol": "BTC",
            "name": "Bitcoin",
            "market_cap_rank": 1,
            "price_inr": 8500000.0,
            "price_usd": 101796.4,
            "high_24h_inr": 8600000.0,
            "low_24h_inr": 8400000.0,
            "price_change_24h_percent": 1.25,
            "market_cap_inr": 160000000000.0,
            "volume_24h_inr": 5000000000.0,
            "price_date": "2026-11-04",
            "status": "ACTIVE",
            "updated_at": "2026-11-04 00:00:00Z"
        }]
        with patch("modules.crypto.crypto_collector.fetch_coingecko_crypto", return_value=sample_crypto):
            count = sync_crypto(self.conn)
            self.assertEqual(count, 1)

            cursor = self.conn.cursor()
            cursor.execute("SELECT price_inr, market_cap_rank FROM master_crypto WHERE symbol='BTC'")
            row = cursor.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], 8500000.0)
            self.assertEqual(row[1], 1)


if __name__ == "__main__":
    unittest.main()
