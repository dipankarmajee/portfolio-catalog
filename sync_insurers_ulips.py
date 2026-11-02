"""
Service: sync_insurers_ulips.py
"""

import os
import sys
import sqlite3
import logging
from datetime import datetime

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
    
    # Clean out any old/dirty records where the insurer_name was an article title
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
        conn.execute("DELETE FROM master_insurers WHERE reg_number = 'LIFEINSURA' OR insurer_name LIKE '%Terms and Conditions%'")

    insurers = scrape_registered_life_insurers()
    now_iso = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%SZ")

    if insurers:
        rows = [
            (
                i.get("insurer_id", f"INS_{i['reg_number']}"),
                i["insurer_name"],
                str(i["reg_number"]),
                i.get("status", "ACTIVE"),
                now_iso
            )
            for i in insurers if "reg_number" in i and "insurer_name" in i
        ]
        with conn:
            conn.execute("DELETE FROM master_insurers")
            conn.executemany("""
                INSERT INTO master_insurers (insurer_id, insurer_name, reg_number, status, updated_at)
                VALUES (?, ?, ?, ?, ?)
            """, rows)
        logging.info("Refreshed master_insurers with %d valid entities.", len(rows))
    else:
        logging.info("Scraper returned 0 records during diagnostic inspection.")

    conn.close()

if __name__ == "__main__":
    sync()