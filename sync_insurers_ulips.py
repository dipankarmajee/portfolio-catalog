"""
Service: sync_insurers_ulips.py
"""

import os
import sys
import sqlite3
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [SYNC_INSURERS] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

from scrapers.irdai_scraper import scrape_registered_life_insurers

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "master_insurers_ulips.sqlite")

def sync():
    os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)

    # Completely wipe the table of old navigation links
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
        conn.execute("DELETE FROM master_insurers")
        logging.info("Cleared all stale records from master_insurers.")

    insurers = scrape_registered_life_insurers()
    logging.info("Scraper returned %d records during diagnostic.", len(insurers))
    conn.close()

if __name__ == "__main__":
    sync()