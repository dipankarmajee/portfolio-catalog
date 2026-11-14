"""
modules/fixed_income/sgb_collector.py
Orchestrates Sovereign Gold Bond (SGB) tranche ingestion into SQLite database.
Generates/updates master_sgb_tranches inside master_fixed_income.sqlite.
"""

from datetime import datetime, timezone
import logging
import sqlite3
from typing import Dict, List

from core.database import register_schema_documentation, transaction
from core.schemas import SCHEMA_SGB_TRANCHES
from modules.fixed_income.sgb_scraper import SGBScraper

logger = logging.getLogger(__name__)


def init_sgb_schema(conn: sqlite3.Connection):
    """Initializes schema and indices for master_sgb_tranches."""
    with transaction(conn) as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS master_sgb_tranches (
                uid TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                name TEXT NOT NULL,
                series TEXT NOT NULL,
                issue_date TEXT NOT NULL,
                maturity_date TEXT NOT NULL,
                issue_price REAL NOT NULL,
                coupon_rate REAL NOT NULL DEFAULT 2.50,
                coupon_months TEXT NOT NULL,
                coupon_day INTEGER NOT NULL DEFAULT 1,
                latest_price REAL,
                price_date TEXT,
                status TEXT NOT NULL DEFAULT 'ACTIVE',
                updated_at TEXT NOT NULL
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sgb_symbol ON master_sgb_tranches(symbol)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sgb_name ON master_sgb_tranches(name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sgb_series ON master_sgb_tranches(series)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sgb_status ON master_sgb_tranches(status)")

    register_schema_documentation(conn, "master_sgb_tranches", SCHEMA_SGB_TRANCHES)


def sync_sgb_tranches(conn: sqlite3.Connection) -> int:
    """
    Ingests all Sovereign Gold Bond tranches into master_sgb_tranches table.
    Returns count of tranches synced.
    """
    init_sgb_schema(conn)
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")

    scraper = SGBScraper()
    batch = []
    count = 0

    for tranche in scraper.fetch_all_tranches():
        batch.append((
            tranche["uid"],
            tranche["symbol"],
            tranche["name"],
            tranche["series"],
            tranche["issue_date"],
            tranche["maturity_date"],
            tranche["issue_price"],
            tranche["coupon_rate"],
            tranche["coupon_months"],
            tranche["coupon_day"],
            tranche.get("latest_price"),
            tranche.get("price_date"),
            tranche.get("status", "ACTIVE"),
            now_iso,
        ))

        if len(batch) >= 50:
            _upsert_sgb_batch(conn, batch)
            count += len(batch)
            batch.clear()

    if batch:
        _upsert_sgb_batch(conn, batch)
        count += len(batch)

    logger.info("Successfully synced %d SGB tranches into master_sgb_tranches in SQLite.", count)
    return count


def _upsert_sgb_batch(conn: sqlite3.Connection, batch: List[tuple]):
    """Batch upsert for master_sgb_tranches table."""
    with transaction(conn) as cursor:
        cursor.executemany("""
            INSERT INTO master_sgb_tranches (
                uid, symbol, name, series, issue_date, maturity_date,
                issue_price, coupon_rate, coupon_months, coupon_day,
                latest_price, price_date, status, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(uid) DO UPDATE SET
                symbol = excluded.symbol,
                name = excluded.name,
                series = excluded.series,
                issue_date = excluded.issue_date,
                maturity_date = excluded.maturity_date,
                issue_price = excluded.issue_price,
                coupon_rate = excluded.coupon_rate,
                coupon_months = excluded.coupon_months,
                coupon_day = excluded.coupon_day,
                latest_price = coalesce(excluded.latest_price, master_sgb_tranches.latest_price),
                price_date = coalesce(excluded.price_date, master_sgb_tranches.price_date),
                status = excluded.status,
                updated_at = excluded.updated_at
        """, batch)
