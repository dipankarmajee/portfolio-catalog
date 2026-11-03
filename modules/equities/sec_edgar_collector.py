"""
modules/equities/sec_edgar_collector.py
Official US Public Equities & ETFs collector from the US Securities and Exchange Commission (SEC EDGAR).
"""

from datetime import datetime, timezone
import logging
from typing import Dict, List
import requests

from core.config import DB_EQUITIES_ETFS, SEC_HEADERS
from core.database import get_connection, transaction
from core.enums import AssetClass, Country, Currency, Exchange, InstrumentStatus
from core.text_utils import canonicalize_identifier, clean_english_text
from core.urls import SEC_COMPANY_TICKERS_URL
from modules.equities.nse_collector import init_equities_schema

logger = logging.getLogger(__name__)


def fetch_sec_edgar_equities() -> List[Dict]:
    """
    Fetches the official SEC EDGAR company directory containing all US publicly traded companies.
    Adheres strictly to the SEC fair access user-agent policy.
    """
    logger.info("Connecting to official US SEC EDGAR directory at %s...", SEC_COMPANY_TICKERS_URL)
    session = requests.Session()
    session.headers.update(SEC_HEADERS)

    resp = session.get(SEC_COMPANY_TICKERS_URL, timeout=30)
    resp.raise_for_status()
    raw_data = resp.json()

    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    records = []

    for entry in raw_data.values():
        ticker = str(entry.get("ticker", "")).strip().upper()
        raw_title = str(entry.get("title", "")).strip()
        cik = str(entry.get("cik_str", "")).strip()

        if not ticker or not raw_title:
            continue

        clean_title = clean_english_text(raw_title)

        # Detect ETFs from fund title keywords
        category = AssetClass.STOCK.value
        if any(term in clean_title.upper() for term in [" ETF", "INDEX FUND", "ISHARES", "VANGUARD", "SPDR"]):
            category = AssetClass.ETF.value

        records.append({
            "uid": canonicalize_identifier(f"US_{category}", ticker),
            "symbol": f"US:{ticker}",
            "ticker_symbol": ticker,
            "name": clean_title,
            "category": category,
            "country": Country.UNITED_STATES.value,
            "isin": f"CIK_{cik.zfill(10)}" if cik else None,
            "exchange": Exchange.NASDAQ.value,  # Default US primary exchange
            "currency": Currency.USD.value,
            "latest_close": None,
            "price_date": today_iso,
            "status": InstrumentStatus.ACTIVE.value,
        })

    logger.info("Parsed %d US SEC EDGAR instruments.", len(records))
    return records


def sync_sec_edgar_equities(conn) -> int:
    init_equities_schema(conn)
    records = fetch_sec_edgar_equities()
    if not records:
        logger.warning("No SEC EDGAR records returned.")
        return 0

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    upsert_rows = [
        (
            r["uid"], r["symbol"], r["ticker_symbol"], r["name"], r["category"],
            r["country"], r["isin"], r["exchange"], r["currency"], r["latest_close"],
            r["price_date"], r["status"], now_iso
        )
        for r in records
    ]

    with transaction(conn) as cursor:
        cursor.executemany("""
            INSERT INTO master_equities_etfs (
                uid, symbol, ticker_symbol, name, category, country, isin, exchange,
                currency, latest_close, price_date, status, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                ticker_symbol = excluded.ticker_symbol,
                name = excluded.name,
                category = excluded.category,
                country = excluded.country,
                isin = coalesce(excluded.isin, master_equities_etfs.isin),
                exchange = excluded.exchange,
                currency = excluded.currency,
                price_date = excluded.price_date,
                status = excluded.status,
                updated_at = excluded.updated_at
        """, upsert_rows)

    logger.info("Successfully synced %d US SEC EDGAR instruments.", len(upsert_rows))
    return len(upsert_rows)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    conn = get_connection(DB_EQUITIES_ETFS)
    sync_sec_edgar_equities(conn)
    conn.close()

