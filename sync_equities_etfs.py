"""
Service: sync_equities_etfs.py
Purpose: Synchronizes Equities, ETFs, and Sovereign Gold Bonds (SGBs) into a normalized SQLite table.
Features:
  - External target definition file (no hardcoded tickers in code).
  - Explicit schema documentation table.
  - Safe multi-ticker fetching with currency and exchange attributes.
"""

import os
import json
import sqlite3
import logging
from datetime import datetime
from typing import Dict, List, Optional
import yfinance as yf

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

DB_PATH = os.path.join("data", "master_equities_etfs.sqlite")
FALLBACK_PATH = os.path.join("config", "fallbacks_equities.json")

SCHEMA_DOCS = [
    ("uid", "TEXT", 1, "Deterministic unique ID (e.g. STOCK_RELIANCE, ETF_NIFTYBEES)"),
    ("symbol", "TEXT", 0, "Exchange trading symbol (e.g. RELIANCE.NS, TMPV.NS)"),
    ("name", "TEXT", 0, "Official entity / security description"),
    ("category", "TEXT", 0, "Asset class (STOCK, ETF, or SGB)"),
    ("isin", "TEXT", 0, "International Securities Identification Number"),
    ("exchange", "TEXT", 0, "Primary exchange identifier (NSE or BSE)"),
    ("currency", "TEXT", 0, "Trading currency (INR)"),
    ("latest_close", "REAL", 0, "Last traded closing price / NAV equivalent"),
    ("price_date", "TEXT", 0, "Date of valuation in ISO 8601 format (YYYY-MM-DD)"),
    ("status", "TEXT", 0, "Trading status (ACTIVE or DELISTED)"),
    ("updated_at", "TEXT", 0, "Synchronization UTC timestamp (ISO 8601)")
]

def init_db(conn: sqlite3.Connection):
    """Creates tables and documents every column."""
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS master_equities_etfs (
                uid TEXT PRIMARY KEY,
                symbol TEXT NOT NULL UNIQUE,
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
        conn.execute("CREATE INDEX IF NOT EXISTS idx_markets_category ON master_equities_etfs(category)")

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

def load_instrument_registry() -> List[Dict]:
    """Reads target tracking instruments from config/fallbacks_equities.json."""
    if not os.path.exists(FALLBACK_PATH):
        logging.warning("Instrument registry %s not found. No tickers to sync.", FALLBACK_PATH)
        return []
    try:
        with open(FALLBACK_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception as e:
        logging.error("Failed to read %s: %s. Returning empty registry.", FALLBACK_PATH, e)
        return []

def sync():
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    registry = load_instrument_registry()
    if not registry:
        logging.info("Registry is empty. Nothing to fetch.")
        conn.close()
        return

    now_iso = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%SZ")
    upsert_rows = []

    for item in registry:
        symbol = item.get("symbol")
        uid = item.get("uid", f"MKT_{symbol}")
        name = item.get("name", symbol)
        category = item.get("category", "STOCK")
        isin = item.get("isin")
        exchange = item.get("exchange", "NSE")
        currency = item.get("currency", "INR")

        price = None
        price_date = None
        status = "ACTIVE"

        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="5d")
            if not hist.empty:
                last_row = hist.iloc[-1]
                price = round(float(last_row["Close"]), 2)
                price_date = hist.index[-1].strftime("%Y-%m-%d")
            else:
                status = "INACTIVE"
        except Exception as e:
            logging.warning("Unable to fetch live quote for %s: %s", symbol, e)
            status = "FETCH_FAILED"

        upsert_rows.append((
            uid, symbol, name, category, isin, exchange, currency,
            price, price_date, status, now_iso
        ))

    with conn:
        conn.executemany("""
            INSERT INTO master_equities_etfs (
                uid, symbol, name, category, isin, exchange, currency,
                latest_close, price_date, status, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                name=excluded.name,
                category=excluded.category,
                isin=excluded.isin,
                exchange=excluded.exchange,
                currency=excluded.currency,
                latest_close=excluded.latest_close,
                price_date=excluded.price_date,
                status=excluded.status,
                updated_at=excluded.updated_at
        """, upsert_rows)

    conn.close()
    logging.info("Markets (Equities/ETFs/SGBs) sync completed with %d entries.", len(upsert_rows))

if __name__ == "__main__":
    sync()