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

from scrapers.irdai_scraper import scrape_all_regulated_entities

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "master_insurers_ulips.sqlite")

REGULATED_ENTITIES_DOCS = [
    ("entity_id", "TEXT", 1, "Unique primary key: ENT_{reg_number}"),
    ("entity_name", "TEXT", 0, "Registered entity corporate description"),
    ("reg_number", "TEXT", 0, "Statutory registration or license number"),
    ("category", "TEXT", 0, "IRDAI regulatory sector classification"),
    ("website", "TEXT", 0, "Official public web portal URL"),
    ("source_url", "TEXT", 0, "Source IRDAI directory registry endpoint"),
    ("status", "TEXT", 0, "Regulatory status (ACTIVE)"),
    ("updated_at", "TEXT", 0, "Pipeline sync UTC timestamp (ISO 8601)")
]

INSURERS_DOCS = [
    ("insurer_id", "TEXT", 1, "Unique primary key: INS_{reg_number}"),
    ("insurer_name", "TEXT", 0, "Registered life insurance corporation name"),
    ("reg_number", "TEXT", 0, "Official statutory registration number"),
    ("category", "TEXT", 0, "Statutory class (LIFE_INSURERS)"),
    ("website", "TEXT", 0, "Official corporate portal URL"),
    ("source_url", "TEXT", 0, "Source IRDAI registry endpoint"),
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
            CREATE TABLE IF NOT EXISTS master_regulated_entities (
                entity_id TEXT PRIMARY KEY,
                entity_name TEXT NOT NULL,
                reg_number TEXT NOT NULL,
                category TEXT NOT NULL,
                website TEXT,
                source_url TEXT,
                status TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(category, reg_number, entity_name)
            )
        """)
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
        
        all_docs = [('master_regulated_entities', *d) for d in REGULATED_ENTITIES_DOCS] + \
                   [('master_insurers', *d) for d in INSURERS_DOCS] + \
                   [('master_ulip_funds', *d) for d in ULIP_DOCS]
        conn.executemany("""
            INSERT OR REPLACE INTO _schema_documentation 
            (table_name, column_name, data_type, is_primary_key, description)
            VALUES (?, ?, ?, ?, ?)
        """, all_docs)

def sync():
    os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    now_iso = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%SZ")

    all_entities: List[Dict] = []
    try:
        all_entities = scrape_all_regulated_entities()
        logging.info("Dynamic scrape succeeded: %d total entities collected.", len(all_entities))
    except Exception as exc:
        logging.error("Failed to scrape regulated entities: %s", exc)

    if all_entities:
        entity_rows = [
            (
                e["entity_id"],
                e["entity_name"],
                str(e["reg_number"]),
                e["category"],
                e.get("website", ""),
                e.get("source_url", ""),
                e.get("status", "ACTIVE"),
                now_iso
            )
            for e in all_entities
        ]
        with conn:
            conn.executemany("""
                INSERT OR REPLACE INTO master_regulated_entities 
                (entity_id, entity_name, reg_number, category, website, source_url, status, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, entity_rows)
        logging.info("Saved %d total regulated entities to master_regulated_entities.", len(entity_rows))

        # Filter and deduplicate Life Insurers strictly by registration number
        life_insurers_map: Dict[str, Dict] = {}
        for e in all_entities:
            if "LIFE" in e["category"] and "NON_LIFE" not in e["category"]:
                reg = str(e["reg_number"]).strip()
                if reg not in life_insurers_map or (reg.isdigit() and not life_insurers_map[reg]["reg_number"].isdigit()):
                    life_insurers_map[reg] = e

        deduped_life_insurers = list(life_insurers_map.values())
        logging.info("Deduplicated to %d unique Life Insurers.", len(deduped_life_insurers))

        insurer_rows = [
            (
                f"INS_{i['reg_number']}",
                i["entity_name"],
                str(i["reg_number"]),
                i["category"],
                i.get("website", ""),
                i.get("source_url", ""),
                i.get("status", "ACTIVE"),
                now_iso
            )
            for i in deduped_life_insurers
        ]

        with conn:
            conn.execute("DELETE FROM master_insurers")
            conn.executemany("""
                INSERT OR REPLACE INTO master_insurers 
                (insurer_id, insurer_name, reg_number, category, website, source_url, status, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, insurer_rows)
        logging.info("Successfully refreshed master_insurers with %d verified Life Insurers.", len(insurer_rows))

    else:
        logging.warning("No records returned. Table master_insurers remains unchanged.")

    conn.close()

if __name__ == "__main__":
    sync()