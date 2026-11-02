"""
Service: sync_insurers_ulips.py
Purpose: Ingests all IRDAI regulated entities and ULIP funds into SQLite.
"""

import os
import sys
import sqlite3
import logging
from datetime import datetime
from typing import List, Dict

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [SYNC_ENTITIES] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

from scrapers.irdai_scraper import scrape_registered_life_insurers

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "master_insurers_ulips.sqlite")

def init_db(conn: sqlite3.Connection):
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS master_insurers (
                insurer_id TEXT PRIMARY KEY,
                insurer_name TEXT NOT NULL,
                reg_number TEXT NOT NULL UNIQUE,
                category TEXT NOT NULL DEFAULT 'LIFE_INSURERS',
                website TEXT,
                source_url TEXT,
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

def sync():
    os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    insurers: List[Dict] = []
    try:
        insurers = scrape_registered_life_insurers()
        logging.info("Scrape succeeded: %d records extracted.", len(insurers))
    except Exception as exc:
        logging.error("Scraper execution failed: %s", exc)

    now_iso = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%SZ")

    if insurers:
        rows = [
            (
                i.get("insurer_id", f"INS_{i['reg_number']}"),
                i["insurer_name"],
                str(i["reg_number"]),
                i.get("category", "LIFE_INSURERS"),
                i.get("website", ""),
                i.get("source_url", ""),
                i.get("status", "ACTIVE"),
                now_iso
            )
            for i in insurers if "reg_number" in i and "insurer_name" in i
        ]
        with conn:
            # Clean purge to wipe any previous dirty placeholders
            conn.execute("DELETE FROM master_insurers")
            conn.executemany("""
                INSERT INTO master_insurers (insurer_id, insurer_name, reg_number, category, website, source_url, status, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, rows)
        logging.info("Cleaned and refreshed master_insurers with %d verified corporate records.", len(rows))
    else:
        logging.warning("No records returned. Table master_insurers remains unchanged.")

    conn.close()

if __name__ == "__main__":
    sync()