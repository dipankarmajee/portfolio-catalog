"""
Service: sync_mutual_funds.py
Source: AMFI India Official Feed (amfiindia.com)
Pattern: Dynamic fetch first -> Optional fallback on failure -> Graceful exit.
"""

import os
import json
import sqlite3
import logging
from datetime import datetime
from typing import List, Optional, Tuple, Dict
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "master_mutual_funds.sqlite")
FALLBACK_PATH = os.path.join(BASE_DIR, "config", "fallbacks_mutual_funds.json")
AMFI_NAV_URL = "https://www.amfiindia.com/spages/NAVAll.txt"

SCHEMA_DOCS = [
    ("uid", "TEXT", 1, "Unique primary key: MF_{scheme_code}"),
    ("scheme_code", "TEXT", 0, "Official AMFI numeric scheme code"),
    ("isin_div_payout_or_growth", "TEXT", 0, "ISIN Growth / Payout"),
    ("isin_div_reinvestment", "TEXT", 0, "ISIN Reinvestment"),
    ("scheme_name", "TEXT", 0, "Full scheme description"),
    ("amc_name", "TEXT", 0, "Asset Management Company"),
    ("category", "TEXT", 0, "SEBI Scheme Classification"),
    ("nav", "REAL", 0, "Latest Net Asset Value per unit in INR"),
    ("nav_date", "TEXT", 0, "Valuation date in ISO format (YYYY-MM-DD)"),
    ("status", "TEXT", 0, "ACTIVE if valid positive NAV present, else INACTIVE"),
    ("updated_at", "TEXT", 0, "Pipeline sync UTC timestamp (ISO 8601)")
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
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mf_status ON master_mutual_funds(status)")

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

def fetch_live_amfi() -> List[Tuple]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/plain, */*"
    }
    logging.info("Streaming master NAV catalog from AMFI (%s)...", AMFI_NAV_URL)
    resp = requests.get(AMFI_NAV_URL, headers=headers, timeout=60)
    resp.raise_for_status()

    records = []
    current_category = "General"
    current_amc = "Unknown AMC"
    now_iso = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%SZ")

    for raw_line in resp.text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        parts = [p.strip() for p in line.split(";")]

        # Header rows: Category or AMC name
        if len(parts) == 1:
            header_val = parts[0]
            if any(term in header_val for term in ["Mutual Fund", "AMC", "Asset Management"]):
                current_amc = header_val
            else:
                current_category = header_val
            continue

        # Data rows start with numeric scheme code
        if len(parts) >= 5 and parts[0].isdigit():
            scheme_code = parts[0]
            raw_date = parts[-1].strip()
            raw_nav = parts[-2].strip()

            isin_payout = parts[1].strip() if len(parts) >= 6 and parts[1].strip() not in ("", "-") else None
            isin_reinv = parts[2].strip() if len(parts) >= 6 and parts[2].strip() not in ("", "-") else None

            if len(parts) == 6:
                scheme_name = parts[3].strip()
            elif len(parts) > 6:
                scheme_name = "; ".join(parts[3:-2]).strip()
            else:
                scheme_name = parts[1].strip()

            nav = None
            if raw_nav and raw_nav not in ("", "-"):
                try:
                    val = float(raw_nav.replace(",", ""))
                    if val > 0:
                        nav = val
                except ValueError:
                    nav = None

            nav_date = parse_iso_date(raw_date)
            status = "ACTIVE" if (nav is not None and nav_date is not None) else "INACTIVE"

            records.append((
                f"MF_{scheme_code}", scheme_code, isin_payout, isin_reinv,
                scheme_name, current_amc, current_category, nav, nav_date,
                status, now_iso
            ))

    return records

def load_optional_fallback() -> List[Tuple]:
    """Loads fallback mutual funds if available; otherwise returns an empty list."""
    if not os.path.exists(FALLBACK_PATH):
        logging.info("Optional fallback file %s not found.", FALLBACK_PATH)
        return []
    try:
        with open(FALLBACK_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, list):
                return []
            now_iso = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%SZ")
            records = []
            for item in data:
                sc = str(item.get("scheme_code", "")).strip()
                if not sc:
                    continue
                nav_val = item.get("nav")
                records.append((
                    item.get("uid", f"MF_{sc}"),
                    sc,
                    item.get("isin_div_payout_or_growth"),
                    item.get("isin_div_reinvestment"),
                    item.get("scheme_name", "Unknown Scheme"),
                    item.get("amc_name", "Unknown AMC"),
                    item.get("category", "General"),
                    nav_val,
                    item.get("nav_date"),
                    item.get("status", "ACTIVE" if nav_val else "INACTIVE"),
                    now_iso
                ))
            return records
    except Exception as e:
        logging.warning("Failed parsing fallback file %s: %s", FALLBACK_PATH, e)
        return []

def sync():
    os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    records: List[Tuple] = []

    # Step 1: Live fetch
    try:
        records = fetch_live_amfi()
        active_count = sum(1 for r in records if r[9] == "ACTIVE")
        logging.info("Dynamic AMFI fetch succeeded: %d records (%d ACTIVE).", len(records), active_count)
    except Exception as e:
        logging.error("Live AMFI fetch failed: %s. Checking optional fallback...", e)
        records = load_optional_fallback()
        if records:
            logging.info("Using fallback data: %d records loaded.", len(records))
        else:
            logging.warning("No fallback records found. Database will remain unchanged.")

    # Step 2: Ingest records if available
    if records:
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
        logging.info("Mutual funds catalog updated successfully.")

    conn.close()

if __name__ == "__main__":
    sync()