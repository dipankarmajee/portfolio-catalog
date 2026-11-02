"""
Service: sync_insurers_ulips.py
Purpose: Ingests dynamic life insurers and ULIP catalogs into SQLite.
"""

import os
import sys
import json
import sqlite3
import logging
from datetime import datetime
from typing import List, Dict, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [SYNC_INSURERS] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

from scrapers.irdai_scraper import scrape_registered_life_insurers

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "master_insurers_ulips.sqlite")
FALLBACK_PATH = os.path.join(BASE_DIR, "config", "fallbacks_insurers_ulips.json")

INSURERS_DOCS = [
    ("insurer_id", "TEXT", 1, "Unique primary key: INS_{reg_number}"),
    ("insurer_name", "TEXT", 0, "Registered life insurance corporation name"),
    ("reg_number", "TEXT", 0, "Official IRDAI statutory registration number"),
    ("status", "TEXT", 0, "Regulatory status (ACTIVE)"),
    ("updated_at", "TEXT", 0, "Pipeline sync UTC timestamp (ISO 8601)")
]

ULIP_DOCS = [
    ("sfin", "TEXT", 1, "16-character Segregated Fund Identification Number"),
    ("fund_name", "TEXT", 0, "Official public fund name"),
    ("insurer_id", "TEXT", 0, "Foreign key -> master_insurers.insurer_id"),
    ("inception_date", "TEXT", 0, "Launch date (YYYY-MM-DD)"),
    ("latest_nav", "REAL", 0, "Latest closing NAV per unit"),
    ("nav_date", "TEXT", 0, "Valuation date (YYYY-MM-DD)"),
    ("status", "TEXT", 0, "Fund status (ACTIVE / CLOSED)"),
    ("updated_at", "TEXT", 0, "Pipeline sync UTC timestamp (ISO 8601)")
]

def init_db(conn: sqlite3.Connection):
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS master_insurers (
                insurer_id TEXT PRIMARY KEY,
                insurer_name TEXT NOT NULL,
                reg_number TEXT NOT NULL UNIQUE,
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

def load_optional_fallback() -> Tuple[List[Dict], List[Dict]]:
    if not os.path.exists(FALLBACK_PATH):
        return [], []
    try:
        with open(FALLBACK_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            insurers = data.get("insurers", []) if isinstance(data, dict) else []
            funds = data.get("ulip_funds", []) if isinstance(data, dict) else []
            return insurers, funds
    except Exception as e:
        logging.warning("Fallback load error: %s", e)
        return [], []

def sync():
    os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    insurers: List[Dict] = []
    ulip_funds: List[Dict] = []

    try:
        insurers = scrape_registered_life_insurers()
        logging.info("Dynamic scrape succeeded: %d insurers gathered.", len(insurers))
    except Exception as exc:
        logging.error("Dynamic scrape failed: %s. Checking optional fallback...", exc)
        insurers, ulip_funds = load_optional_fallback()

    now_iso = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%SZ")

    if insurers:
        rows = [
            (
                i.get("insurer_id", f"INS_{i.get('reg_number')}"),
                i["insurer_name"],
                str(i["reg_number"]),
                i.get("status", "ACTIVE"),
                now_iso
            )
            for i in insurers if "reg_number" in i and "insurer_name" in i
        ]
        with conn:
            # Clear old/dirty records so stale entries are removed
            conn.execute("DELETE FROM master_insurers")
            conn.executemany("""
                INSERT INTO master_insurers (insurer_id, insurer_name, reg_number, status, updated_at)
                VALUES (?, ?, ?, ?, ?)
            """, rows)
        logging.info("Cleaned and refreshed master_insurers with %d valid entities.", len(rows))
    else:
        logging.warning("No insurer records available. Database remains unchanged.")

    if ulip_funds:
        fund_rows = [
            (
                f["sfin"],
                f["fund_name"],
                f["insurer_id"],
                f.get("inception_date"),
                f.get("latest_nav"),
                f.get("nav_date"),
                f.get("status", "ACTIVE"),
                now_iso
            )
            for f in ulip_funds if "sfin" in f and "fund_name" in f and "insurer_id" in f
        ]
        with conn:
            conn.executemany("""
                INSERT INTO master_ulip_funds (sfin, fund_name, insurer_id, inception_date, latest_nav, nav_date, status, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sfin) DO UPDATE SET
                    fund_name=excluded.fund_name,
                    latest_nav=excluded.latest_nav,
                    nav_date=excluded.nav_date,
                    status=excluded.status,
                    updated_at=excluded.updated_at
            """, fund_rows)
        logging.info("Updated %d ULIP fund records.", len(fund_rows))

    conn.close()

if __name__ == "__main__":
    sync()