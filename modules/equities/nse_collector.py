"""
modules/equities/nse_collector.py
Synchronizes all active Indian Equities, ETFs, and Sovereign Gold Bonds (SGBs)
directly from the official National Stock Exchange (NSE) directories.
"""

import csv
from datetime import datetime, timezone
import io
import logging

from core.constants import NSE_EXCLUDED_SERIES
from core.database import register_schema_documentation, transaction
from core.enums import AssetClass, Country, Currency, Exchange, InstrumentStatus
from core.http_client import create_resilient_session
from core.schemas import SCHEMA_EQUITIES
from core.text_utils import clean_english_text, generate_canonical_uid
from core.urls import NSE_EQUITIES_URL, NSE_ETF_URL
from modules.equities.bhavcopy import fetch_nse_bhavcopy_prices

logger = logging.getLogger(__name__)


def init_equities_schema(conn):
    with transaction(conn) as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS master_equities_etfs (
                uid TEXT PRIMARY KEY,
                symbol TEXT NOT NULL UNIQUE,
                ticker_symbol TEXT,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                country TEXT NOT NULL,
                isin TEXT,
                exchange TEXT NOT NULL,
                currency TEXT NOT NULL,
                latest_close REAL,
                price_date TEXT,
                status TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_eq_symbol ON master_equities_etfs(symbol)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_eq_isin ON master_equities_etfs(isin)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_eq_cat ON master_equities_etfs(category)")
    register_schema_documentation(conn, "master_equities_etfs", SCHEMA_EQUITIES)


def sync_nse_equities_and_etfs(conn) -> int:
    init_equities_schema(conn)
    session = create_resilient_session()
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Dynamic closing price lookup
    bhavcopy_prices = fetch_nse_bhavcopy_prices()
    instruments = []

    # 1. Official NSE Listed Equities
    logger.info("Connecting to official NSE directory at %s...", NSE_EQUITIES_URL)
    resp = session.get(NSE_EQUITIES_URL, timeout=30)
    resp.raise_for_status()

    reader = csv.DictReader(io.StringIO(resp.text))
    for row in reader:
        symbol = (row.get("SYMBOL") or "").strip()
        series = (row.get(" SERIES") or row.get("SERIES") or "").strip().upper()
        if not symbol or series in NSE_EXCLUDED_SERIES:
            continue

        name = clean_english_text(row.get("NAME OF COMPANY") or symbol)
        isin = (row.get(" ISIN NUMBER") or row.get("ISIN NUMBER") or "").strip()
        is_sgb = symbol.startswith("SGB")
        cat = AssetClass.SGB.value if is_sgb else AssetClass.STOCK.value
        uid = generate_canonical_uid(cat, symbol)
        close_price = bhavcopy_prices.get(symbol.upper())

        instruments.append((
            uid, symbol, symbol, name, cat, Country.INDIA.value, isin,
            Exchange.NSE.value, Currency.INR.value, close_price,
            today_iso if close_price else None, InstrumentStatus.ACTIVE.value, now_iso
        ))

    # 2. Official NSE Listed ETFs
    try:
        resp_etf = session.get(NSE_ETF_URL, timeout=20)
        if resp_etf.status_code == 200:
            etf_reader = csv.DictReader(io.StringIO(resp_etf.text))
            for row in etf_reader:
                sym = (row.get("Symbol") or row.get("SYMBOL") or "").strip()
                if not sym:
                    continue
                name = clean_english_text(row.get("Security Name") or row.get("NAME OF COMPANY") or sym)
                isin = (row.get("ISIN") or row.get("ISIN NUMBER") or "").strip()
                uid = generate_canonical_uid(AssetClass.ETF.value, sym)
                close_price = bhavcopy_prices.get(sym.upper())

                instruments.append((
                    uid, sym, sym, name, AssetClass.ETF.value, Country.INDIA.value, isin,
                    Exchange.NSE.value, Currency.INR.value, close_price,
                    today_iso if close_price else None, InstrumentStatus.ACTIVE.value, now_iso
                ))
    except Exception as e:
        logger.warning("Optional NSE ETF directory parse note: %s", e)

    # Ingest into SQLite
    with transaction(conn) as cursor:
        cursor.executemany("""
            INSERT INTO master_equities_etfs (
                uid, symbol, ticker_symbol, name, category, country, isin, exchange,
                currency, latest_close, price_date, status, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(uid) DO UPDATE SET
                ticker_symbol = excluded.ticker_symbol,
                name = excluded.name,
                category = excluded.category,
                isin = excluded.isin,
                latest_close = coalesce(excluded.latest_close, master_equities_etfs.latest_close),
                price_date = coalesce(excluded.price_date, master_equities_etfs.price_date),
                status = excluded.status,
                updated_at = excluded.updated_at
        """, instruments)

    logger.info("Successfully synced %d NSE instruments.", len(instruments))
    return len(instruments)


sync_nse_equities = sync_nse_equities_and_etfs

