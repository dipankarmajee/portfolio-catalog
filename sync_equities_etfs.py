"""
Service: sync_equities_etfs.py
Format: SEBI Official UDiFF Standard (BSE CM Bhavcopy)
"""

import io
import os
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
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
}

SCHEMA_DOCS = [
    ("uid", "TEXT", 1, "Unique primary key: STOCK_{scrip}, ETF_{scrip}, or SGB_{scrip}"),
    ("symbol", "TEXT", 0, "BSE Scrip Code (FinInstrmId)"),
    ("ticker_symbol", "TEXT", 0, "Harmonized Ticker Symbol (TckrSymb)"),
    ("name", "TEXT", 0, "Corporate Security Description (FinInstrmNm)"),
    ("category", "TEXT", 0, "Asset Category (STOCK, ETF, SGB)"),
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

def fetch_bse_udiff() -> List[Dict]:
    today = datetime.utcnow()

    # Search past 7 days to cover weekends and exchange holidays
    for delta in range(7):
        target_dt = today - timedelta(days=delta)
        if target_dt.weekday() == 6:  # Skip Sundays
            continue

        date_compact = target_dt.strftime("%Y%m%d")
        iso_date = target_dt.strftime("%Y-%m-%d")

        url = f"https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{date_compact}_F_0000.CSV"
        logging.info("Checking official UDiFF Bhavcopy for date %s...", iso_date)

        try:
            resp = requests.get(url, headers=HEADERS, timeout=25)
            if resp.status_code == 200 and len(resp.content) > 1000:
                df = pd.read_csv(io.StringIO(resp.text))
                
                # Check for standard UDiFF columns
                if "FinInstrmId" not in df.columns or "ClsPric" not in df.columns:
                    continue

                records = []
                for _, row in df.iterrows():
                    sc_code = str(row["FinInstrmId"]).strip()
                    tckr = str(row.get("TckrSymb", "")).strip()
                    name = str(row.get("FinInstrmNm", tckr)).strip()
                    isin = str(row.get("ISIN", "")).strip() if pd.notna(row.get("ISIN")) else None

                    category = "STOCK"
                    if "ETF" in name or "ETF" in tckr:
                        category = "ETF"
                    elif "SGB" in name or tckr.startswith("SGB"):
                        category = "SGB"

                    try:
                        cls_price = round(float(row["ClsPric"]), 2)
                    except (ValueError, TypeError):
                        cls_price = None

                    records.append({
                        "uid": f"{category}_{sc_code}",
                        "symbol": sc_code,
                        "ticker_symbol": tckr,
                        "name": name,
                        "category": category,
                        "isin": isin,
                        "exchange": "BSE",
                        "currency": "INR",
                        "latest_close": cls_price,
                        "price_date": iso_date,
                        "status": "ACTIVE" if cls_price else "INACTIVE"
                    })

                logging.info("Extracted %d securities from UDiFF Bhavcopy (%s).", len(records), iso_date)
                return records
        except Exception as e:
            logging.debug("Date %s skipped: %s", iso_date, e)

    return []

def sync():
    os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    records = fetch_bse_udiff()
    if not records:
        logging.warning("No recent Bhavcopy found. Master table untouched.")
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
    logging.info("Equities sync completed: %d records updated.", len(upsert_rows))

if __name__ == "__main__":
    sync()