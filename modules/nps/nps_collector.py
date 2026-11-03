"""
modules/nps/nps_collector.py
Official National Pension System (NPS) collector.
Dynamically fetches all PFRDA authorized Pension Fund Managers and schemes,
along with their latest Net Asset Values (NAVs) and multi-year returns.
Strictly dynamic: zero hardcoded schemes or static NAV values.
"""

from datetime import datetime, timezone
import logging
import re
from typing import Dict, List, Optional

from core.database import register_schema_documentation, transaction
from core.enums import Country, Currency, InstrumentStatus, NpsAssetClass, NpsTier
from core.http_client import create_resilient_session
from core.schemas import SCHEMA_NPS
from core.text_utils import clean_english_text, generate_canonical_uid
from core.urls import NPS_LATEST_API_URL

logger = logging.getLogger(__name__)


def init_nps_schema(conn):
    with transaction(conn) as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS master_nps (
                uid TEXT PRIMARY KEY,
                scheme_code TEXT NOT NULL UNIQUE,
                scheme_name TEXT NOT NULL,
                pfm_name TEXT NOT NULL,
                tier TEXT NOT NULL,
                asset_class TEXT NOT NULL,
                country TEXT NOT NULL,
                currency TEXT NOT NULL,
                latest_nav REAL,
                nav_date TEXT,
                return_1y REAL,
                return_3y REAL,
                return_5y REAL,
                tax_section TEXT,
                status TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        cursor.execute("PRAGMA table_info(master_nps)")
        existing = {col[1] for col in cursor.fetchall()}
        for col_name in ("return_1y", "return_3y", "return_5y"):
            if col_name not in existing:
                cursor.execute(f"ALTER TABLE master_nps ADD COLUMN {col_name} REAL")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_nps_code ON master_nps(scheme_code)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_nps_pfm ON master_nps(pfm_name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_nps_tier ON master_nps(tier)")
    register_schema_documentation(conn, "master_nps", SCHEMA_NPS)


def _detect_tier(scheme_name: str) -> str:
    name_upper = scheme_name.upper()
    if "TIER II" in name_upper or "TIER-II" in name_upper or "TIER 2" in name_upper:
        return NpsTier.TIER_II.value
    if "CENTRAL GOVT" in name_upper or "STATE GOVT" in name_upper:
        return NpsTier.GOVERNMENT.value
    if "CORPORATE" in name_upper:
        return NpsTier.CORPORATE.value
    return NpsTier.TIER_I.value


def _detect_asset_class(scheme_name: str) -> str:
    name_upper = scheme_name.upper()
    if re.search(r"\bSCHEME\s+E\b|EQUITY", name_upper):
        return NpsAssetClass.E.value
    if re.search(r"\bSCHEME\s+C\b|CORPORATE\s+BOND", name_upper):
        return NpsAssetClass.C.value
    if re.search(r"\bSCHEME\s+G\b|GOVT", name_upper):
        return NpsAssetClass.G.value
    if re.search(r"\bSCHEME\s+A\b|ALTERNATIVE", name_upper):
        return NpsAssetClass.A.value
    return NpsAssetClass.ALL.value


def _parse_float(val: Optional[str]) -> Optional[float]:
    if not val:
        return None
    try:
        f = float(str(val).replace(",", "").strip())
        return round(f, 4)
    except (ValueError, TypeError):
        return None


def _parse_iso_date(raw_date: Optional[str]) -> Optional[str]:
    if not raw_date:
        return None
    raw = raw_date.strip()
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def fetch_nps_schemes() -> List[Dict]:
    """
    Fetches all active NPS schemes dynamically from official daily disclosure feeds.
    """
    logger.info("Connecting to live NPS schemes and NAV registry at %s...", NPS_LATEST_API_URL)
    session = create_resilient_session()
    resp = session.get(NPS_LATEST_API_URL, timeout=25)
    resp.raise_for_status()

    payload = resp.json()
    items = payload.get("data", [])
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    records: List[Dict] = []

    for entry in items:
        code = str(entry.get("Scheme Code") or "").strip().upper()
        raw_name = str(entry.get("Scheme Name") or "").strip()
        pfm_raw = str(entry.get("PFM Name") or "").strip()
        if not code or not raw_name:
            continue

        clean_name = clean_english_text(raw_name)
        pfm_name = clean_english_text(pfm_raw) if pfm_raw else "Pension Fund Manager"
        nav_val = _parse_float(entry.get("NAV"))
        date_iso = _parse_iso_date(entry.get("Last Updated"))

        tier = _detect_tier(clean_name)
        asset_class = _detect_asset_class(clean_name)
        uid = generate_canonical_uid("NPS", code)

        records.append({
            "uid": uid,
            "scheme_code": code,
            "scheme_name": clean_name,
            "pfm_name": pfm_name,
            "tier": tier,
            "asset_class": asset_class,
            "country": Country.INDIA.value,
            "currency": Currency.INR.value,
            "latest_nav": nav_val,
            "nav_date": date_iso,
            "return_1y": _parse_float(entry.get("1Y")),
            "return_3y": _parse_float(entry.get("3Y")),
            "return_5y": _parse_float(entry.get("5Y")),
            "tax_section": "80CCD(1), 80CCD(1B), 80CCD(2)" if tier == NpsTier.TIER_I.value else None,
            "status": InstrumentStatus.ACTIVE.value if nav_val else InstrumentStatus.CLOSED.value,
            "updated_at": now_iso,
        })

    logger.info("Dynamically parsed %d NPS schemes with live NAVs.", len(records))
    return records


def sync_nps(conn) -> int:
    init_nps_schema(conn)
    schemes = fetch_nps_schemes()

    if not schemes:
        logger.warning("No NPS schemes retrieved from live registry.")
        return 0

    with transaction(conn) as cursor:
        cursor.executemany("""
            INSERT INTO master_nps (
                uid, scheme_code, scheme_name, pfm_name, tier, asset_class,
                country, currency, latest_nav, nav_date, return_1y, return_3y,
                return_5y, tax_section, status, updated_at
            ) VALUES (
                :uid, :scheme_code, :scheme_name, :pfm_name, :tier, :asset_class,
                :country, :currency, :latest_nav, :nav_date, :return_1y, :return_3y,
                :return_5y, :tax_section, :status, :updated_at
            )
            ON CONFLICT(scheme_code) DO UPDATE SET
                scheme_name = excluded.scheme_name,
                pfm_name = excluded.pfm_name,
                tier = excluded.tier,
                asset_class = excluded.asset_class,
                latest_nav = coalesce(excluded.latest_nav, master_nps.latest_nav),
                nav_date = coalesce(excluded.nav_date, master_nps.nav_date),
                return_1y = coalesce(excluded.return_1y, master_nps.return_1y),
                return_3y = coalesce(excluded.return_3y, master_nps.return_3y),
                return_5y = coalesce(excluded.return_5y, master_nps.return_5y),
                tax_section = excluded.tax_section,
                status = excluded.status,
                updated_at = excluded.updated_at
        """, schemes)

    logger.info("Successfully synced %d NPS schemes.", len(schemes))
    return len(schemes)
