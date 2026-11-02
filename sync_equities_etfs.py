"""
Service: sync_equities_etfs.py
Source: Official BSE Daily Bhavcopy & Listed Security Directory
"""

import io
import os
import zipfile
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import List, Dict
import requests
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "master_equities_etfs.sqlite")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9"
}

SCHEMA_DOCS = [
    ("uid", "TEXT", 1, "Unique primary key: STOCK_{scrip}, ETF_{scrip}, or SGB_{scrip}"),
    ("symbol", "TEXT", 0, "BSE Scrip Code"),
    ("ticker_symbol", "TEXT", 0, "Trading Ticker Symbol"),
    ("name", "TEXT", 0, "Security / Corporate Name"),
    ("category", "TEXT", 0, "Asset Class (STOCK, ETF, SGB)"),
    ("isin", "TEXT", 0, "ISIN Code"),
    ("exchange", "TEXT", 0, "Exchange (BSE)"),
    ("currency", "TEXT", 0, "Trading Currency (INR)"),
    ("latest_close", "REAL", 0, "Closing Price in INR"),
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

def fetch_bse_records() -> List[Dict]:
    today = datetime.utcnow()
    session = requests.Session()
    session.headers.update(HEADERS)

    # Search the last 7 calendar days to guarantee hitting an open trading session
    for delta in range(7):
        target_dt = today - timedelta(days=delta)
        if target_dt.weekday() == 6:  # Skip Sundays
            continue

        dd = target_dt.strftime("%d")
        mm = target_dt.strftime("%m")
        yy = target_dt.strftime("%y")
        iso_date = target_dt.strftime("%Y-%m-%d")

        url = f"https://www.bseindia.com/download/BhavCopy/Equity/EQ{dd}{mm}{yy}_CSV.ZIP"
        logging.info("Checking BSE Bhavcopy for %s...", iso_date)

        try:
            resp = session.get(url, timeout=20)
            if resp.status_code == 200 and len(resp.content) > 5000:
                records = []
                with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
                    csv_name = z.namelist()[0]
                    with z.open(csv_name) as f:
                        df = pd.read_csv(f)
                        for _, row in df.iterrows():
                            sc_code = str(row["SC_CODE"]).strip()
                            sc_name = str(row["SC_NAME"]).strip()
                            sc_type = str(row.get("SC_TYPE", "")).strip().upper()
                            isin = str(row.get("ISIN_CODE", "")).strip() if "ISIN_CODE" in row and pd.notna(row["ISIN_CODE"]) else None

                            category = "STOCK"
                            if "ETF" in sc_name or sc_type == "ETF":
                                category = "ETF"
                            elif "SGB" in sc_name or sc_name.startswith("SGB"):
                                category = "SGB"

                            try:
                                close_val = round(float(row["CLOSE"]), 2)
                            except (ValueError, TypeError):
                                close_val = None

                            records.append({
                                "uid": f"{category}_{sc_code}",
                                "symbol": sc_code,
                                "ticker_symbol": sc_name.split()[0] if sc_name else sc_code,
                                "name": sc_name,
                                "category": category,
                                "isin": isin,
                                "exchange": "BSE",
                                "currency": "INR",
                                "latest_close": close_val,
                                "price_date": iso_date,
                                "status": "ACTIVE" if close_val else "INACTIVE"
                            })
                logging.info("Loaded %d securities from Bhavcopy date %s.", len(records), iso_date)
                return records
        except Exception as e:
            logging.debug("Date %s skipped: %s", iso_date, e)

    return []

def sync():
    os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    records = fetch_bse_records()
    if not records:
        logging.warning("No recent Bhavcopy found. Table unmodified.")
        conn.close()
        return

    now_iso = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%SZ")
    upsert_rows = [
        (
            r["uid"], r["symbol"], r["ticker_symbol"], r["name"], r["category"],
            r["isin"], r["exchange"], r["currency"],
            r["latest_close"], r["price_date"], r["status"], now_iso
        )
        for r in records
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
                latest_close=excluded.latest_close,
                price_date=excluded.price_date,
                status=excluded.status,
                updated_at=excluded.updated_at
        """, upsert_rows)

    conn.close()