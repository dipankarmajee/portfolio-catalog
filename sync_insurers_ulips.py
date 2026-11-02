"""
Service: sync_insurers_ulips.py
Purpose: Synchronizes registered life insurers and ULIP SFIN funds into a normalized SQLite catalog.
Features:
  - Separate structured tables for Insurers and ULIP SFIN Funds.
  - Automatic column documentation (_schema_documentation).
  - External fallback & registry loader without in-code static data.
"""

import os
import json
import sqlite3
import logging
from datetime import datetime
from typing import Dict, List, Tuple
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

DB_PATH = os.path.join("data", "master_insurers_ulips.sqlite")
FALLBACK_PATH = os.path.join("config", "fallbacks_insurers_ulips.json")

INSURERS_DOCS = [
    ("insurer_id", "TEXT", 1, "Unique statutory insurer code (e.g. HDF111, SBI111)"),
    ("insurer_name", "TEXT", 0, "Registered life insurance corporation name"),
    ("reg_number", "TEXT", 0, "IRDAI statutory registration sequence number"),
    ("status", "TEXT", 0, "Regulatory status (ACTIVE or SUSPENDED)"),
    ("updated_at", "TEXT", 0, "Sync timestamp in UTC (ISO 8601)")
]

ULIP_DOCS = [
    ("sfin", "TEXT", 1, "16-character Segregated Fund Identification Number"),
    ("fund_name", "TEXT", 0, "Official public fund name"),
    ("insurer_id", "TEXT", 0, "Foreign key linking to master_insurers.insurer_id"),
    ("inception_date", "TEXT", 0, "Statutory fund allotment launch date (YYYY-MM-DD)"),
    ("latest_nav", "REAL", 0, "Latest declared closing NAV per unit"),
    ("nav_date", "TEXT", 0, "Valuation date in ISO 8601 format (YYYY-MM-DD)"),
    ("status", "TEXT", 0, "Fund status (ACTIVE or CLOSED)"),
    ("updated_at", "TEXT", 0, "Sync timestamp in UTC (ISO 8601)")
]

def init_db(conn: sqlite3.Connection):
    """Creates distinct tables and populates self-documenting catalog metadata."""
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS master_insurers (
                insurer_id TEXT PRIMARY KEY,
                insurer_name TEXT NOT NULL,
                reg_number TEXT,
                status TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS master_ulip_funds (
                sfin TEXT PRIMARY KEY,
                fund_name TEXT NOT NULL,
                insurer_id TEXT NOT NULL,
                inception_date TEXT,
                latest_nav REAL,
                nav_date TEXT,
                status TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (insurer_id) REFERENCES master_insurers(insurer_id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ulip_insurer ON master_ulip_funds(insurer_id)")

        # Schema documentation table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS _schema_documentation (
                table_name TEXT NOT NULL,
                column_name TEXT NOT NULL,
                data_type TEXT NOT NULL,
                is_primary_key INTEGER NOT NULL,
                description TEXT NOT NULL,
                PRIMARY KEY (table_name, column_name)
            )
        """)

        all_docs = [('master_insurers', *d) for d in INSURERS_DOCS] + \
                   [('master_ulip_funds', *d) for d in ULIP_DOCS]

        conn.executemany("""
            INSERT OR REPLACE INTO _schema_documentation 
            (table_name, column_name, data_type, is_primary_key, description)
            VALUES (?, ?, ?, ?, ?)
        """, all_docs)

def load_external_definitions() -> Tuple[List[Dict], List[Dict]]:
    """Loads insurers and ULIP fund targets from config file safely."""
    if not os.path.exists(FALLBACK_PATH):
        logging.info("Optional configuration %s not found. Proceeding with blank defaults.", FALLBACK_PATH)
        return [], []
    try:
        with open(FALLBACK_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            insurers = data.get("insurers", [])
            funds = data.get("ulip_funds", [])
            return insurers, funds
    except Exception as e:
        logging.warning("Error reading %s: %s. Continuing with empty lists.", FALLBACK_PATH, e)
        return [], []

def sync():
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    insurers_list, funds_list = load_external_definitions()
    now_iso = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%SZ")

    # 1. Upsert Insurers
    insurer_rows = []
    for ins in insurers_list:
        insurer_rows.append((
            ins["insurer_id"],
            ins["insurer_name"],
            ins.get("reg_number"),
            ins.get("status", "ACTIVE"),
            now_iso
        ))

    if insurer_rows:
        with conn:
            conn.executemany("""
                INSERT INTO master_insurers (insurer_id, insurer_name, reg_number, status, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(insurer_id) DO UPDATE SET
                    insurer_name=excluded.insurer_name,
                    reg_number=excluded.reg_number,
                    status=excluded.status,
                    updated_at=excluded.updated_at
            """, insurer_rows)

    # 2. Upsert ULIP SFIN Funds
    fund_rows = []
    for f in funds_list:
        fund_rows.append((
            f["sfin"],
            f["fund_name"],
            f["insurer_id"],
            f.get("inception_date"),
            f.get("latest_nav"),
            f.get("nav_date"),
            f.get("status", "ACTIVE"),
            now_iso
        ))

    if fund_rows:
        with conn:
            conn.executemany("""
                INSERT INTO master_ulip_funds (sfin, fund_name, insurer_id, inception_date, latest_nav, nav_date, status, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sfin) DO UPDATE SET
                    fund_name=excluded.fund_name,
                    insurer_id=excluded.insurer_id,
                    inception_date=excluded.inception_date,
                    latest_nav=excluded.latest_nav,
                    nav_date=excluded.nav_date,
                    status=excluded.status,
                    updated_at=excluded.updated_at
            """, fund_rows)

    conn.close()
    logging.info("Insurers and ULIPs sync finished: %d insurers, %d funds processed.", len(insurer_rows), len(fund_rows))

if __name__ == "__main__":
    sync()