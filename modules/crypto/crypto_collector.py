"""
modules/crypto/crypto_collector.py
Official Crypto Assets collector.
Dynamically fetches the top 100 liquid digital assets by market capitalization in INR and USD
via CoinGecko and CoinCap market feeds.
Strictly dynamic: zero hardcoded prices or static fallback lists.
"""

from datetime import datetime, timezone
import logging
from typing import Dict, List, Optional
import requests

from core.database import register_schema_documentation, transaction
from core.enums import InstrumentStatus
from core.http_client import create_resilient_session
from core.schemas import SCHEMA_CRYPTO
from core.text_utils import clean_english_text, generate_canonical_uid
from core.urls import COINCAP_ASSETS_URL, COINGECKO_TOP_URL, USD_INR_EXCHANGE_RATE_URL

logger = logging.getLogger(__name__)


def fetch_live_usd_inr_rate(session: requests.Session) -> Optional[float]:
    """
    Dynamically fetches live USD/INR exchange rate from official financial market feed.
    """
    try:
        resp = session.get(USD_INR_EXCHANGE_RATE_URL, timeout=10)
        if resp.status_code == 200:
            meta = resp.json().get("chart", {}).get("result", [{}])[0].get("meta", {})
            price = meta.get("regularMarketPrice")
            if price and float(price) > 0:
                return float(price)
    except Exception as e:
        logger.debug("Live USD/INR exchange rate query notice: %s", e)
    return None


def init_crypto_schema(conn):
    with transaction(conn) as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS master_crypto (
                uid TEXT PRIMARY KEY,
                symbol TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                market_cap_rank INTEGER,
                price_inr REAL,
                price_usd REAL,
                high_24h_inr REAL,
                low_24h_inr REAL,
                price_change_24h_percent REAL,
                market_cap_inr REAL,
                volume_24h_inr REAL,
                price_date TEXT,
                status TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        cursor.execute("PRAGMA table_info(master_crypto)")
        existing = {col[1] for col in cursor.fetchall()}
        for col_name, col_type in [
            ("price_change_24h_percent", "REAL"),
            ("market_cap_inr", "REAL"),
            ("volume_24h_inr", "REAL"),
            ("price_date", "TEXT"),
        ]:
            if col_name not in existing:
                cursor.execute(f"ALTER TABLE master_crypto ADD COLUMN {col_name} {col_type}")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_crypto_sym ON master_crypto(symbol)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_crypto_rank ON master_crypto(market_cap_rank)")
    register_schema_documentation(conn, "master_crypto", SCHEMA_CRYPTO)


def fetch_coingecko_crypto() -> List[Dict]:
    """
    Fetches the top 100 liquid digital assets from CoinGecko.
    """
    logger.info("Connecting to live crypto market feed (%s)...", COINGECKO_TOP_URL)
    session = create_resilient_session()
    resp = session.get(COINGECKO_TOP_URL, timeout=25)
    resp.raise_for_status()

    coins = resp.json()
    records: List[Dict] = []
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    usd_inr_rate = fetch_live_usd_inr_rate(session)

    for c in coins:
        symbol = str(c.get("symbol", "")).strip().upper()
        name = clean_english_text(c.get("name", symbol))
        if not symbol:
            continue

        price_inr = c.get("current_price")
        price_usd = round(price_inr / usd_inr_rate, 4) if (price_inr and usd_inr_rate) else None

        records.append({
            "uid": generate_canonical_uid("CRYPTO", symbol),
            "symbol": symbol,
            "name": name,
            "market_cap_rank": c.get("market_cap_rank"),
            "price_inr": price_inr,
            "price_usd": price_usd,
            "high_24h_inr": c.get("high_24h"),
            "low_24h_inr": c.get("low_24h"),
            "price_change_24h_percent": c.get("price_change_percentage_24h"),
            "market_cap_inr": c.get("market_cap"),
            "volume_24h_inr": c.get("total_volume"),
            "price_date": today_iso,
            "status": InstrumentStatus.ACTIVE.value,
            "updated_at": now_iso,
        })

    logger.info("Dynamically parsed %d crypto assets from CoinGecko.", len(records))
    return records


def fetch_coincap_fallback() -> List[Dict]:
    """
    Fetches liquid digital assets from CoinCap.
    """
    logger.info("Querying CoinCap fallback feed at %s...", COINCAP_ASSETS_URL)
    session = create_resilient_session()
    resp = session.get(COINCAP_ASSETS_URL, timeout=20)
    resp.raise_for_status()

    data = resp.json().get("data", [])
    records: List[Dict] = []
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    usd_inr_rate = fetch_live_usd_inr_rate(session)

    for item in data:
        symbol = str(item.get("symbol", "")).strip().upper()
        name = clean_english_text(item.get("name", symbol))
        price_usd = float(item.get("priceUsd", 0)) or None
        price_inr = round(price_usd * usd_inr_rate, 2) if (price_usd and usd_inr_rate) else None
        rank = int(item.get("rank", 0)) or None

        records.append({
            "uid": generate_canonical_uid("CRYPTO", symbol),
            "symbol": symbol,
            "name": name,
            "market_cap_rank": rank,
            "price_inr": price_inr,
            "price_usd": price_usd,
            "high_24h_inr": None,
            "low_24h_inr": None,
            "price_change_24h_percent": float(item.get("changePercent24Hr", 0)) or None,
            "market_cap_inr": float(item.get("marketCapUsd", 0)) * usd_inr_rate if (item.get("marketCapUsd") and usd_inr_rate) else None,
            "volume_24h_inr": float(item.get("volumeUsd24Hr", 0)) * usd_inr_rate if (item.get("volumeUsd24Hr") and usd_inr_rate) else None,
            "price_date": today_iso,
            "status": InstrumentStatus.ACTIVE.value,
            "updated_at": now_iso,
        })

    logger.info("Dynamically parsed %d crypto assets from CoinCap.", len(records))
    return records


def sync_crypto(conn) -> int:
    init_crypto_schema(conn)

    assets: List[Dict] = []
    try:
        assets = fetch_coingecko_crypto()
    except Exception as e:
        logger.warning("CoinGecko dynamic fetch failed (%s); trying CoinCap...", e)
        try:
            assets = fetch_coincap_fallback()
        except Exception as err:
            logger.error("CoinCap dynamic fetch failed: %s", err)

    if not assets:
        logger.warning("No crypto assets retrieved from live feeds.")
        return 0

    with transaction(conn) as cursor:
        cursor.executemany("""
            INSERT INTO master_crypto (
                uid, symbol, name, market_cap_rank, price_inr, price_usd,
                high_24h_inr, low_24h_inr, price_change_24h_percent,
                market_cap_inr, volume_24h_inr, price_date, status, updated_at
            ) VALUES (
                :uid, :symbol, :name, :market_cap_rank, :price_inr, :price_usd,
                :high_24h_inr, :low_24h_inr, :price_change_24h_percent,
                :market_cap_inr, :volume_24h_inr, :price_date, :status, :updated_at
            )
            ON CONFLICT(symbol) DO UPDATE SET
                name = excluded.name,
                market_cap_rank = coalesce(excluded.market_cap_rank, master_crypto.market_cap_rank),
                price_inr = coalesce(excluded.price_inr, master_crypto.price_inr),
                price_usd = coalesce(excluded.price_usd, master_crypto.price_usd),
                high_24h_inr = coalesce(excluded.high_24h_inr, master_crypto.high_24h_inr),
                low_24h_inr = coalesce(excluded.low_24h_inr, master_crypto.low_24h_inr),
                price_change_24h_percent = coalesce(excluded.price_change_24h_percent, master_crypto.price_change_24h_percent),
                market_cap_inr = coalesce(excluded.market_cap_inr, master_crypto.market_cap_inr),
                volume_24h_inr = coalesce(excluded.volume_24h_inr, master_crypto.volume_24h_inr),
                price_date = coalesce(excluded.price_date, master_crypto.price_date),
                status = excluded.status,
                updated_at = excluded.updated_at
        """, assets)

    logger.info("Successfully synced %d crypto assets.", len(assets))
    return len(assets)
