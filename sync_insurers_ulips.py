"""
Service: sync_insurers_ulips.py (100% Dynamic)
Source: Life Insurance Council Member Registry
"""

import os
import re
import sqlite3
import logging
from datetime import datetime
from typing import List, Dict
import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "master_insurers_ulips.sqlite")

COUNCIL_MEMBERS_URL = "https://www.lifeinscouncil.org/members.aspx"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

INSURERS_DOCS = [
    ("insurer_id", "TEXT", 1, "Unique Insurer Identifier"),
    ("insurer_name", "TEXT", 0, "Registered Life Insurance Corporation Name"),
    ("reg_number", "TEXT", 0, "IRDAI Registration Sequence Number"),
    ("status", "TEXT", 0, "Regulatory Status (ACTIVE / INACTIVE)"),
    ("updated_at", "TEXT", 0, "Sync Timestamp (ISO 8601)")
]

ULIP_DOCS = [
    ("sfin", "TEXT", 1, "16-character Segregated Fund Identification Number"),
    ("fund_name", "TEXT", 0, "Official Fund Description"),
    ("insurer_id", "TEXT", 0, "Foreign key -> master_insurers.insurer_id"),
    ("inception_date", "TEXT", 0, "Inception Date (YYYY-MM-DD)"),
    ("latest_nav", "REAL", 0, "Latest declared NAV"),
    ("nav_date", "TEXT", 0, "Valuation Date (YYYY-MM-DD)"),
    ("status", "TEXT", 0, "Fund Status (ACTIVE / CLOSED)"),
    ("updated_at", "TEXT", 0, "Sync Timestamp (ISO 8601)")
]

def init_db(conn: sqlite3.Connection):
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

def fetch_dynamic_insurers() -> List[Dict]:
    logging.info("Harvesting life insurers from Life Insurance Council directory...")
    try:
        resp = requests.get(COUNCIL_MEMBERS_URL, headers=HEADERS, timeout=25)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        
        insurers = []
        for tag in soup.find_all("a", href=True):
            href = tag["href"]
            text = tag.get_text(strip=True)
            if "members_details.aspx" in href and len(text) > 4:
                # Extract registration or create unique slug
                raw_id = href.split("=")[-1] if "=" in href else re.sub(r"[^A-Za-z0-9]", "", text)[:8].upper()
                insurers.append({
                    "insurer_id": raw_id,
                    "insurer_name": text,
                    "reg_number": raw_id if raw_id.isdigit() else None,
                    "status": "ACTIVE"
                })
        
        # Deduplicate by insurer_id
        unique_insurers = {i["insurer_id"]: i for i in insurers}.values()
        return list(unique_insurers)
    except Exception as e:
        logging.error("Failed to scrape Life Insurance Council: %s", e)
        return []

def sync():
    os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    insurers = fetch_dynamic_insurers()
    now_iso = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%SZ")

    if insurers:
        rows = [
            (i["insurer_id"], i["insurer_name"], i["reg_number"], i["status"], now_iso)
            for i in insurers
        ]
        with conn:
            conn.executemany("""
                INSERT INTO master_insurers (insurer_id, insurer_name, reg_number, status, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(insurer_id) DO UPDATE SET
                    insurer_name=excluded.insurer_name,
                    status=excluded.status,
                    updated_at=excluded.updated_at
            """, rows)

    conn.close()
    logging.info("Synced %d insurers dynamically.", len(insurers))

if __name__ == "__main__":
    sync()