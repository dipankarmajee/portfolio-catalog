"""
modules/commodities/ibja_collector.py
Official Commodities & Bullion rates collector.
Dynamically scrapes official India Bullion and Jewellers Association (IBJA) benchmark rates
for 24K, 22K, 18K Gold, Silver 999, and Platinum, plus global spot benchmarks.
Strictly dynamic: zero hardcoded prices or static fallback lists.
"""

from datetime import datetime, timezone
import logging
import re
from typing import Dict, List, Optional
import requests
from bs4 import BeautifulSoup

from core.constants import BULLION_METADATA
from core.database import register_schema_documentation, transaction
from core.enums import (
    CommodityPurity,
    CommodityType,
    CommodityUnit,
    Country,
    Currency,
    InstrumentStatus,
)
from core.http_client import create_resilient_session
from core.schemas import SCHEMA_COMMODITIES
from core.text_utils import generate_canonical_uid
from core.urls import GLOBAL_SPOT_GOLD_URL, GLOBAL_SPOT_SILVER_URL, IBJA_RATES_PORTAL_URL

logger = logging.getLogger(__name__)


def init_commodities_schema(conn):
    with transaction(conn) as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS master_commodities (
                uid TEXT PRIMARY KEY,
                symbol TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                commodity_type TEXT NOT NULL,
                purity TEXT NOT NULL,
                unit TEXT NOT NULL,
                country TEXT NOT NULL,
                currency TEXT NOT NULL,
                rate REAL NOT NULL,
                rate_date TEXT,
                high_all_time REAL,
                low_all_time REAL,
                source TEXT NOT NULL,
                status TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_comm_symbol ON master_commodities(symbol)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_comm_type ON master_commodities(commodity_type)")
    register_schema_documentation(conn, "master_commodities", SCHEMA_COMMODITIES)


def fetch_ibja_rates() -> List[Dict]:
    """
    Scrapes live IBJA rates dynamically from the official rates board.
    """
    logger.info("Connecting to official IBJA rates board at %s...", IBJA_RATES_PORTAL_URL)
    session = create_resilient_session()
    resp = session.get(IBJA_RATES_PORTAL_URL, timeout=20)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    records: List[Dict] = []
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for tr in soup.find_all("tr"):
        cells = [td.get_text().strip() for td in tr.find_all(["td", "th"])]
        if len(cells) < 2:
            continue

        raw_title = cells[0].upper().strip()
        meta = BULLION_METADATA.get(raw_title)
        if not meta:
            continue

        symbol, name, comm_type, purity, unit = meta
        rate_val: Optional[float] = None

        # Prioritize PM rate (cells[2]), fallback to AM rate (cells[1])
        for cell in reversed(cells[1:3]):
            cleaned = re.sub(r"[^\d.]", "", cell)
            try:
                val = float(cleaned)
                if val > 0:
                    rate_val = round(val, 2)
                    break
            except ValueError:
                continue

        if rate_val:
            records.append({
                "uid": generate_canonical_uid("COMMODITY", symbol),
                "symbol": symbol,
                "name": name,
                "commodity_type": comm_type,
                "purity": purity,
                "unit": unit,
                "country": Country.INDIA.value,
                "currency": Currency.INR.value,
                "rate": rate_val,
                "rate_date": today_iso,
                "high_all_time": rate_val,
                "low_all_time": rate_val,
                "source": "IBJA",
                "status": InstrumentStatus.ACTIVE.value,
                "updated_at": now_iso,
            })

    # Global spot USD benchmarks (Gold & Silver per Troy Ounce)
    spot_sources = [
        ("GOLD", "GOLD_SPOT_USD", "Global Spot Gold (USD / Oz)", GLOBAL_SPOT_GOLD_URL),
        ("SILVER", "SILVER_SPOT_USD", "Global Spot Silver (USD / Oz)", GLOBAL_SPOT_SILVER_URL),
    ]
    for m_type, sym, name, spot_url in spot_sources:
        try:
            spot_resp = session.get(spot_url, timeout=5)
            if spot_resp.status_code == 200:
                meta_data = spot_resp.json().get("chart", {}).get("result", [{}])[0].get("meta", {})
                price = meta_data.get("regularMarketPrice")
                if price and float(price) > 0:
                    val = round(float(price), 2)
                    records.append({
                        "uid": generate_canonical_uid("COMMODITY", sym),
                        "symbol": sym,
                        "name": name,
                        "commodity_type": m_type,
                        "purity": "999 (Spot)",
                        "unit": CommodityUnit.TROY_OUNCE.value,
                        "country": Country.GLOBAL.value,
                        "currency": Currency.USD.value,
                        "rate": val,
                        "rate_date": today_iso,
                        "high_all_time": val,
                        "low_all_time": val,
                        "source": "LBMA",
                        "status": InstrumentStatus.ACTIVE.value,
                        "updated_at": now_iso,
                    })
        except Exception as e:
            logger.debug("Spot rate lookup for %s notice: %s", m_type, e)

    logger.info("Dynamically parsed %d bullion rates from IBJA.", len(records))
    return records


def sync_commodities(conn) -> int:
    init_commodities_schema(conn)
    rates = fetch_ibja_rates()

    if not rates:
        logger.warning("No commodity benchmark rates retrieved from live board.")
        return 0

    with transaction(conn) as cursor:
        cursor.executemany("""
            INSERT INTO master_commodities (
                uid, symbol, name, commodity_type, purity, unit, country,
                currency, rate, rate_date, high_all_time, low_all_time,
                source, status, updated_at
            ) VALUES (
                :uid, :symbol, :name, :commodity_type, :purity, :unit, :country,
                :currency, :rate, :rate_date, :high_all_time, :low_all_time,
                :source, :status, :updated_at
            )
            ON CONFLICT(uid) DO UPDATE SET
                rate = excluded.rate,
                rate_date = excluded.rate_date,
                high_all_time = max(master_commodities.high_all_time, excluded.rate),
                low_all_time = min(master_commodities.low_all_time, excluded.rate),
                status = excluded.status,
                updated_at = excluded.updated_at
        """, rates)

    logger.info("Successfully synced %d dynamic commodity benchmarks.", len(rates))
    return len(rates)
