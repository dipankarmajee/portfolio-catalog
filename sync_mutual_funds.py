"""
Service: sync_mutual_funds.py
Purpose: Synchronizes the complete AMFI mutual funds catalog into a normalized SQLite database.
Features:
  - Self-documenting table metadata (_schema_documentation).
  - Resilient external fallback JSON reader.
  - Clean AMC & Category inheritance from AMFI stream headers.
  - Strict ISO 8601 date formatting.
"""

import os
import json
import sqlite3
import logging
from datetime import datetime
from typing import Dict, List, Optional
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

DB_PATH = os.path.join("data", "master_mutual_funds.sqlite")
FALLBACK_PATH = os.path.join("config", "fallbacks_mutual_funds.json")
AMFI_NAV_URL = "https://www.amfiindia.com/spages/NAVAll.txt"

SCHEMA_DOCS = [
    ("uid", "TEXT", 1, "Unique primary key composed of MF_{scheme_code}"),
    ("scheme_code", "TEXT", 0, "Official AMFI numeric scheme code"),
    ("isin_div_payout_or_growth", "TEXT", 0, "ISIN for Growth or Dividend Payout plan"),
    ("isin_div_reinvestment", "TEXT", 0, "ISIN for Dividend Reinvestment plan"),
    ("scheme_name", "TEXT", 0, "Full official scheme description and plan name"),
    ("amc_name", "TEXT", 0, "Name of the Asset Management Company (AMC)"),
    ("category", "TEXT", 0, "SEBI mutual fund asset category (e.g., Equity Scheme - Flexi Cap)"),
    ("nav", "REAL", 0, "Latest calculated Net Asset Value per unit in INR"),
    ("nav_date", "TEXT", 0, "Valuation date in ISO 8601 format (YYYY-MM-DD)"),
    ("status", "TEXT", 0, "Operational status (ACTIVE or INACTIVE)"),
    ("updated_at", "TEXT", 0, "Pipeline synchronization UTC timestamp (ISO 8601)")
]

def init_db(conn: sqlite3.Connection):
    """Initializes normalized tables and runtime schema documentation."""
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
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mf_scheme_name ON master_mutual_funds(scheme_name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mf_isin ON master_mutual_funds(isin_div_payout_or_growth)")

        # Self-documenting table
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

def load_optional_fallbacks() -> List[Dict]:
    """Gracefully loads optional external fallbacks without throwing errors."""
    if not os.path.exists(FALLBACK_PATH):
        logging.info("Optional fallback file %s not found. Proceeding with clean live sync.", FALLBACK_PATH)
        return []
    try:
        with open(FALLBACK_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception as e:
        logging.warning("Could not parse fallback file %s: %s. Continuing with empty fallbacks.", FALLBACK_PATH, e)
        return []

def parse_iso_date(raw_date: str) -> Optional[str]:
    """Standardizes various AMFI date formats to ISO YYYY-MM-DD."""
    if not raw_date:
        return None
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw_date.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None

def fetch_amfi_catalog() -> List[Dict]:
    """Downloads and normalizes the active AMFI flat text file stream."""
    headers = {"User-Agent": "Mozilla/5.0"}
    logging.info("Fetching master daily NAV flat file from AMFI...")
    resp = requests.get(AMFI_NAV_URL, headers=headers, timeout=45)
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
            # Header line: could be AMC Name or Category
            header_val = parts[0]
            if "Mutual Fund" in header_val or "AMC" in header_val:
                current_amc = header_val
            else:
                current_category = header_val
            continue

        if len(parts) >= 6:
            scheme_code = parts[0]
            if not scheme_code.isdigit():
                continue

            isin_payout = parts[1] if parts[1] and parts[1] != "-" else None
            isin_reinv = parts[2] if parts[2] and parts[2] != "-" else None
            scheme_name = parts[3]
            
            try:
                nav = float(parts[4]) if parts[4] and parts[4] != "-" else None
            except ValueError:
                nav = None

            nav_date = parse_iso_date(parts[5])

            records.append({
                "uid": f"MF_{scheme_code}",
                "scheme_code": scheme_code,
                "isin_div_payout_or_growth": isin_payout,
                "isin_div_reinvestment": isin_reinv,
                "scheme_name": scheme_name,
                "amc_name": current_amc,
                "category": current_category,
                "nav": nav,
                "nav_date": nav_date,
                "status": "ACTIVE" if nav is not None else "INACTIVE",
                "updated_at": now_iso
            })

    return records

def sync():
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    # 1. Load Live Records
    records = fetch_amfi_catalog()
    logging.info("Parsed %d live mutual fund records from AMFI.", len(records))

    # 2. Merge with Optional Fallbacks (External overrides)
    fallbacks = load_optional_fallbacks()
    fallback_map = {f["scheme_code"]: f for f in fallbacks if "scheme_code" in f}
    
    upsert_rows = []
    for r in records:
        sc = r["scheme_code"]
        if sc in fallback_map:
            r.update(fallback_map[sc])
        upsert_rows.append((
            r["uid"], r["scheme_code"], r["isin_div_payout_or_growth"],
            r["isin_div_reinvestment"], r["scheme_name"], r["amc_name"],
            r["category"], r["nav"], r["nav_date"], r["status"], r["updated_at"]
        ))

    # 3. Batch Write
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
        """, upsert_rows)

    conn.close()
    logging.info("Mutual funds sync completed successfully.")

if __name__ == "__main__":
    sync()