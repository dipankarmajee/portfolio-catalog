"""
Service: sync_equities_etfs.py
Source: Official NSE Listed Securities Directory (archives.nseindia.com)
Pattern: Dynamic fetch first -> Optional fallback on failure -> Graceful exit.
"""

import io
import os
import sys
import json
import sqlite3
import logging
from datetime import datetime
from typing import List, Dict
import requests
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [SYNC_EQUITIES] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "master_equities_etfs.sqlite")
FALLBACK_PATH = os.path.join(BASE_DIR, "config", "fallbacks_equities.json")

NSE_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive"
}

SCHEMA_DOCS = [
    ("uid", "TEXT", 1, "Unique primary key: STOCK_{symbol}, ETF_{symbol}, or SGB_{symbol}"),
    ("symbol", "TEXT", 0, "NSE Trading Ticker Symbol"),
    ("ticker_symbol", "TEXT", 0, "Harmonized Ticker Symbol"),
    ("name", "TEXT", 0, "Corporate Security Description"),
    ("category", "TEXT", 0, "Asset Class (STOCK, ETF, SGB)"),
    ("isin", "TEXT", 0, "ISIN Code"),
    ("exchange", "TEXT", 0, "Exchange (NSE)"),
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

def fetch_live_equities() -> List[Dict]:
    logging.info("Connecting to official equity directory at %s...", NSE_URL)
    session = requests.Session()
    session.headers.update(HEADERS)

    # Warm up session cookies on home domain to pass Akamai bot protection
    try:
        session.get("https://www.nseindia.com", timeout=15)
    except Exception as e:
        logging.warning("Pre-flight handshake warning: %s", e)

    resp = session.get(NSE_URL, timeout=30)
    logging.info("HTTP Status Code: %d | Content Length: %d bytes", resp.status_code, len(resp.content))
    resp.raise_for_status()

    df = pd.read_csv(io.StringIO(resp.text))
    # Normalize potential column name spacing in official file
    df.columns = [c.strip() for c in df.columns]

    records = []
    for _, row in df.iterrows():
        sym = str(row.get("SYMBOL", "")).strip()
        name = str(row.get("NAME OF COMPANY", sym)).strip()
        series = str(row.get("SERIES", "")).strip().upper()
        isin = str(row.get("ISIN NUMBER", "")).strip() or None

        if not sym:
            continue

        category = "STOCK"
        if "ETF" in name.upper() or series == "ETF":
            category = "ETF"
        elif "SGB" in name.upper() or series == "GB":
            category = "SGB"

        records.append({
            "uid": f"{category}_{sym}",
            "symbol": sym,
            "ticker_symbol": sym,
            "name": name,
            "category": category,
            "isin": isin,
            "exchange": "NSE",
            "currency": "INR",
            "latest_close": None,
            "price_date": datetime.utcnow().strftime("%Y-%m-%d"),
            "status": "ACTIVE"
        })

    logging.info("Successfully parsed %d instruments from official catalog.", len(records))
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
        logging.warning("Failed loading fallback file: %s", e)
        return []

def sync():
    os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    records: List[Dict] = []
    try:
        records = fetch_live_equities()
    except Exception as exc:
        logging.error("Live fetch failed: %s. Checking optional fallback...", exc)
        records = load_optional_fallback()

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
                r.get("exchange", "NSE"),
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
        logging.info("Equities catalog updated with %d records.", len(upsert_rows))
    else:
        logging.warning("No equity records available to insert. Database remains unchanged.")

    conn.close()

if __name__ == "__main__":
    sync()