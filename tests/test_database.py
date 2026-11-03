"""
tests/test_database.py
Tests for SQLite connection pragmas, transaction atomicity, and schema documentation.
"""

from pathlib import Path
import sqlite3
import tempfile
import unittest

from core.database import get_connection, register_schema_documentation, transaction


class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.sqlite"
        self.conn = get_connection(self.db_path)

    def tearDown(self):
        self.conn.close()
        self.temp_dir.cleanup()

    def test_wal_journal_mode(self):
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA journal_mode;")
        mode = cursor.fetchone()[0]
        self.assertEqual(mode.upper(), "WAL")

    def test_transaction_commit(self):
        with transaction(self.conn) as cursor:
            cursor.execute("CREATE TABLE test_table (id INTEGER PRIMARY KEY, val TEXT);")
            cursor.execute("INSERT INTO test_table (val) VALUES ('alpha');")

        cursor = self.conn.cursor()
        cursor.execute("SELECT val FROM test_table;")
        row = cursor.fetchone()
        self.assertEqual(row[0], "alpha")

    def test_transaction_rollback_on_error(self):
        with transaction(self.conn) as cursor:
            cursor.execute("CREATE TABLE t2 (id INT PRIMARY KEY, val TEXT);")

        with self.assertRaises(Exception):
            with transaction(self.conn) as cursor:
                cursor.execute("INSERT INTO t2 VALUES (1, 'reverted');")
                raise ValueError("Simulated failure")

        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM t2;")
        count = cursor.fetchone()[0]
        self.assertEqual(count, 0)

    def test_schema_documentation_registration(self):
        cols = [
            ("id", "INTEGER", 1, "Primary Key identifier"),
            ("name", "TEXT", 0, "Resource name"),
        ]
        register_schema_documentation(self.conn, "demo_table", cols)

        cursor = self.conn.cursor()
        cursor.execute("SELECT column_name, data_type, is_primary_key, description FROM _schema_documentation WHERE table_name = 'demo_table';")
        rows = cursor.fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][0], "id")
        self.assertEqual(rows[0][2], 1)


if __name__ == "__main__":
    unittest.main()
