"""
Service: sync_mutual_funds.py (100% Dynamic)
Source: AMFI India Centralized NAV Portal
"""

import os
import sqlite3
import logging
from datetime import datetime
from typing import Dict, List, Optional
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "master_mutual_funds.sqlite")
AMFI_NAV_URL = "https://www.amfiindia.com/spages/NAVAll.txt"

SCHEMA_DOCS = [
    ("uid", "TEXT", 1, "Unique primary key: MF_{scheme_code}"),
    ("scheme_code", "TEXT", 0, "Official AMFI numeric scheme code"),
    ("isin_div_payout_or_growth", "TEXT", 0, "ISIN Growth / Payout"),
    ("isin_div_reinvestment", "TEXT", 0, "ISIN Reinvestment"),
    ("scheme_name", "TEXT", 0, "Official Scheme Name"),
    ("amc_name", "TEXT", 0, "Asset Management Company"),
    ("category", "TEXT", 0, "SEBI Scheme Classification"),
    ("nav", "REAL", 0, "Latest declared NAV (INR)"),
    ("nav_date", "TEXT", 0, "Valuation Date (YYYY-MM-DD)"),
    ("status", "TEXT", 0, "ACTIVE if NAV > 0 else INACTIVE"),
    ("updated_at", "TEXT", 0, "Sync Timestamp (ISO 8601)")
]

def init_db(conn: sqlite3.Connection):
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS master_mutual_funds (
                uid TEXT PRIMARY KEY,
                scheme_code TEXT NOT NULL UNIQUE,
                isin_div_payout_or_growth TEXT,
                isin_div_reinvestment TEXT,
                scheme_name TEXT NOT NULL,
                amc_name TEXT,
                category TEXT,
                nav REAL,
                nav_date TEXT,
                status TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mf_code ON master_mutual_funds(scheme_code)")
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
        conn.executemany("""
            INSERT OR REPLACE INTO _schema_documentation 
            (table_name, column_name, data_type, is_primary_key, description)
            VALUES ('master_mutual_funds', ?, ?, ?, ?)
        """, SCHEMA_DOCS)

def parse_iso_date(raw_date: str) -> Optional[str]:
    if not raw_date:
        return None
    raw = raw_date.strip()
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None

def fetch_amfi_catalog() -> List[tuple]:
    headers = {"User-Agent": "Mozilla/5.0"}
    logging.info("Streaming master AMFI feed...")
    resp = requests.get(AMFI_NAV_URL, headers=headers, timeout=60)
    resp.raise_for_status()

    records = []
    current_category = "General"
    current_amc = "Unknown AMC"
    now_iso = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%SZ")

    for line in resp.text.splitlines():
        line = line.strip()
        if not line:
            continue

        parts = [p.strip() for p in line.split(";")]

        if len(parts) == 1:
            header_val = parts[0]
            if any(k in header_val for k in ["Mutual Fund", "AMC", "Asset Management"]):
                current_amc = header_val
            else:
                current_category = header_val
            continue

        if len(parts) >= 5 and parts[0].isdigit():
            scheme_code = parts[0]
            raw_date = parts[-1]
            raw_nav = parts[-2]

            isin_payout = parts[1] if len(parts) >= 6 and parts[1] != "-" else None
            isin_reinv = parts[2] if len(parts) >= 6 and parts[2] != "-" else None

            if len(parts) == 6:
                scheme_name = parts[3]
            elif len(parts) > 6:
                scheme_name = "; ".join(parts[3:-2])
            else:
                scheme_name = parts[1]

            nav = None
            if raw_nav and raw_nav != "-":
                clean_nav = raw_nav.replace(",", "")
                try:
                    nav = float(clean_nav)
                except ValueError:
                    nav = None

            nav_date = parse_iso_date(raw_date)
            status = "ACTIVE" if (nav is not None and nav > 0) else "INACTIVE"

            records.append((
                f"MF_{scheme_code}", scheme_code, isin_payout, isin_reinv,
                scheme_name, current_amc, current_category, nav, nav_date,
                status, now_iso
            ))

    return records

def sync():
    os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    records = fetch_amfi_catalog()
    logging.info("Extracted %d total MF records.", len(records))

    with conn:
        conn.executemany("""
            INSERT INTO master_mutual_funds (
                uid, scheme_code, isin_div_payout_or_growth, isin_div_reinvestment,
                scheme_name, amc_name, category, nav, nav_date, status, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(scheme_code) DO UPDATE SET
                isin_div_payout_or_growth=excluded.isin_div_payout_or_growth,
                isin_div_reinvestment=excluded.isin_div_reinvestment,
                scheme_name=excluded.scheme_name,
                amc_name=excluded.amc_name,
                category=excluded.category,
                nav=excluded.nav,
                nav_date=excluded.nav_date,
                status=excluded.status,
                updated_at=excluded.updated_at
        """, records)

    conn.close()
    logging.info("Master mutual funds table updated successfully.")

if __name__ == "__main__":
    sync()