"""
Service: sync_equities_etfs.py
Source: Official BSE Listed Securities Directory API (api.bseindia.com)
Resilience: Attempts dynamic BSE API fetch first; uses config/fallbacks_equities.json only upon failure.
"""

import os
import json
import sqlite3
import logging
from datetime import datetime
from typing import List, Dict, Tuple
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "master_equities_etfs.sqlite")
FALLBACK_PATH = os.path.join(BASE_DIR, "config", "fallbacks_equities.json")

BSE_LIST_URL = "https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w?Group=&Scripcode=&industry=&segment=Equity&status=Active"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.bseindia.com/"
}

SCHEMA_DOCS = [
    ("uid", "TEXT", 1, "Unique primary key: STOCK_{scrip}, ETF_{scrip}, or SGB_{scrip}"),
    ("symbol", "TEXT", 0, "BSE Numeric Scrip Code"),
    ("ticker_symbol", "TEXT", 0, "Harmonized Ticker Symbol"),
    ("name", "TEXT", 0, "Corporate Security Description"),
    ("category", "TEXT", 0, "Asset Class (STOCK, ETF, SGB)"),
    ("isin", "TEXT", 0, "ISIN Code"),
    ("exchange", "TEXT", 0, "Exchange (BSE)"),
    ("currency", "TEXT", 0, "Currency (INR)"),
    ("latest_close", "REAL", 0, "Closing Market Price"),
    ("price_date", "TEXT", 0, "Valuation Date (YYYY-MM-DD)"),
    ("status", "TEXT", 0, "Trading Status (ACTIVE)"),
    ("updated_at", "TEXT", 0, "Pipeline sync UTC timestamp (ISO 8601)")
]

def init_db(conn: sqlite3.Connection):
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS master_equities_etfs (
                uid TEXT PRIMARY KEY,
                symbol TEXT NOT NULL UNIQUE,
                ticker_symbol TEXT,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                isin TEXT,
                exchange TEXT NOT NULL,
                currency TEXT NOT NULL,
                latest_close REAL,
                price_date TEXT,
                status TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mkt_symbol ON master_equities_etfs(symbol)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mkt_category ON master_equities_etfs(category)")

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
            VALUES ('master_equities_etfs', ?, ?, ?, ?)
        """, SCHEMA_DOCS)

def fetch_live_bse_catalog() -> List[Dict]:
    logging.info("Querying live BSE security directory API...")
    resp = requests.get(BSE_LIST_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    records = []
    for item in data:
        scrip_cd = str(item.get("SCRIP_CD", "")).strip()
        ticker = str(item.get("SCRIP_ID", "")).strip()
        name = str(item.get("Scrip_Name", ticker)).strip()
        isin = str(item.get("ISIN_NUMBER", "")).strip() or None
        status_raw = str(item.get("STATUS", "Active")).strip().upper()

        if not scrip_cd:
            continue

        category = "STOCK"
        if "ETF" in name.upper() or "ETF" in ticker.upper():
            category = "ETF"
        elif "SGB" in name.upper() or ticker.upper().startswith("SGB"):
            category = "SGB"

        records.append({
            "uid": f"{category}_{scrip_cd}",
            "symbol": scrip_cd,
            "ticker_symbol": ticker,
            "name": name,
            "category": category,
            "isin": isin,
            "exchange": "BSE",
            "currency": "INR",
            "latest_close": None,
            "price_date": datetime.utcnow().strftime("%Y-%m-%d"),
            "status": "ACTIVE" if status_raw == "ACTIVE" else "INACTIVE"
        })
    return records

def load_optional_fallback() -> List[Dict]:
    if not os.path.exists(FALLBACK_PATH):
        logging.info("Optional fallback file %s not found.", FALLBACK_PATH)
        return []
    try:
        with open(FALLBACK_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception as e:
        logging.warning("Failed loading fallback file %s: %s.", FALLBACK_PATH, e)
        return []

def sync():
    os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    try:
        records = fetch_live_bse_catalog()
        logging.info("Retrieved %d active securities from live BSE API.", len(records))
    except Exception as e:
        logging.error("Live BSE fetch failed: %s. Checking optional fallback...", e)
        records = load_optional_fallback()
        if records:
            logging.info("Engaging fallback: loaded %d securities from %s.", len(records), FALLBACK_PATH)
        else:
            logging.warning("No fallback records found. Database unchanged.")

    if records:
        now_iso = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%SZ")
        upsert_rows = [
            (
                r.get("uid", f"{r.get('category', 'STOCK')}_{r['symbol']}"),
                r["symbol"],
                r.get("ticker_symbol", r["symbol"]),
                r.get("name", r["symbol"]),
                r.get("category", "STOCK"),
                r.get("isin"),
                r.get("exchange", "BSE"),
                r.get("currency", "INR"),
                r.get("latest_close"),
                r.get("price_date", datetime.utcnow().strftime("%Y-%m-%d")),
                r.get("status", "ACTIVE"),
                now_iso
            )
            for r in records if "symbol" in r
        ]

        with conn:
            conn.executemany("""
                INSERT INTO master_equities_etfs (
                    uid, symbol, ticker_symbol, name, category, isin, exchange, currency,
                    latest_close, price_date, status, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    ticker_symbol=excluded.ticker_symbol,
                    name=excluded.name,
                    category=excluded.category,
                    isin=excluded.isin,
                    price_date=excluded.price_date,
                    status=excluded.status,
                    updated_at=excluded.updated_at
            """, upsert_rows)
        logging.info("BSE catalog synced with %d records.", len(upsert_rows))

    conn.close()

if __name__ == "__main__":
    sync()