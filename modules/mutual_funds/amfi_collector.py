"""
modules/mutual_funds/amfi_collector.py
Official Indian Mutual Funds collector from the Association of Mutual Funds in India (AMFI).
Streams and synchronizes the daily master NAV catalog (~14,500 active schemes).
"""

from datetime import datetime, timezone
import logging
from typing import Dict, List, Optional, Tuple
import requests

from core.database import register_schema_documentation, transaction
from core.enums import Country, Currency, InstrumentStatus
from core.schemas import SCHEMA_MUTUAL_FUNDS
from core.text_utils import canonicalize_identifier, clean_english_text
from core.urls import AMFI_NAV_ALL_URL

logger = logging.getLogger(__name__)


def init_mutual_funds_schema(conn):
    with transaction(conn) as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS master_mutual_funds (
                uid TEXT PRIMARY KEY,
                scheme_code TEXT NOT NULL UNIQUE,
                isin_div_payout_or_growth TEXT,
                isin_div_reinvestment TEXT,
                scheme_name TEXT NOT NULL,
                amc_name TEXT,
                category TEXT,
                country TEXT DEFAULT 'IND',
                currency TEXT DEFAULT 'INR',
                nav REAL,
                nav_date TEXT,
                status TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_mf_code ON master_mutual_funds(scheme_code)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_mf_status ON master_mutual_funds(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_mf_category ON master_mutual_funds(category)")
    register_schema_documentation(conn, "master_mutual_funds", SCHEMA_MUTUAL_FUNDS)


def parse_iso_date(raw_date: str) -> Optional[str]:
    if not raw_date:
        return None
    raw = raw_date.strip()
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def fetch_amfi_mutual_funds() -> List[Dict]:
    logger.info("Streaming master NAV catalog from AMFI (%s)...", AMFI_NAV_ALL_URL)
    resp = requests.get(AMFI_NAV_ALL_URL, timeout=45, stream=True)
    resp.raise_for_status()

    current_category: Optional[str] = None
    current_amc: Optional[str] = None
    records: List[Dict] = []
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")

    for line in resp.iter_lines(decode_unicode=True):
        if not line:
            continue
        line_clean = line.strip()
        if not line_clean:
            continue

        parts = [p.strip() for p in line_clean.split(";")]

        if len(parts) == 1:
            header_val = clean_english_text(parts[0])
            if "Mutual Fund" in header_val:
                current_amc = header_val
            elif header_val and not header_val.startswith("Scheme Code"):
                current_category = header_val
            continue

        if len(parts) >= 6:
            scheme_code = parts[0]
            if not scheme_code.isdigit():
                continue

            isin_growth = parts[1] if parts[1] and parts[1] != "-" else None
            isin_reinv = parts[2] if parts[2] and parts[2] != "-" else None
            base_scheme_name = clean_english_text(parts[3])

            if len(parts) >= 8:
                plan = clean_english_text(parts[4])
                option = clean_english_text(parts[5])
                parts_name = [base_scheme_name]
                if plan and plan.lower() not in base_scheme_name.lower():
                    parts_name.append(plan)
                if option and option.lower() not in base_scheme_name.lower():
                    parts_name.append(option)
                scheme_name = " - ".join(parts_name)
                raw_nav = parts[6]
                raw_date = parts[7]
            else:
                scheme_name = base_scheme_name
                raw_nav = parts[4]
                raw_date = parts[5]

            nav_val: Optional[float] = None
            try:
                nav_float = float(raw_nav)
                if nav_float > 0.0:
                    nav_val = round(nav_float, 4)
            except (ValueError, TypeError):
                pass

            iso_date = parse_iso_date(raw_date)
            status = InstrumentStatus.ACTIVE.value if nav_val is not None else InstrumentStatus.INACTIVE.value

            records.append({
                "uid": canonicalize_identifier("MF", scheme_code),
                "scheme_code": scheme_code,
                "isin_div_payout_or_growth": isin_growth,
                "isin_div_reinvestment": isin_reinv,
                "scheme_name": scheme_name,
                "amc_name": current_amc,
                "category": current_category,
                "country": Country.INDIA.value,
                "currency": Currency.INR.value,
                "nav": nav_val,
                "nav_date": iso_date,
                "status": status,
                "updated_at": now_iso,
            })

    logger.info("Parsed %d AMFI mutual funds.", len(records))
    return records


def sync_amfi_mutual_funds(conn) -> int:
    init_mutual_funds_schema(conn)
    funds = fetch_amfi_mutual_funds()

    batch_size = 1000
    with transaction(conn) as cursor:
        for i in range(0, len(funds), batch_size):
            batch = funds[i:i + batch_size]
            cursor.executemany("""
                INSERT INTO master_mutual_funds (
                    uid, scheme_code, isin_div_payout_or_growth, isin_div_reinvestment,
                    scheme_name, amc_name, category, country, currency, nav,
                    nav_date, status, updated_at
                ) VALUES (
                    :uid, :scheme_code, :isin_div_payout_or_growth, :isin_div_reinvestment,
                    :scheme_name, :amc_name, :category, :country, :currency, :nav,
                    :nav_date, :status, :updated_at
                )
                ON CONFLICT(scheme_code) DO UPDATE SET
                    isin_div_payout_or_growth = excluded.isin_div_payout_or_growth,
                    isin_div_reinvestment = excluded.isin_div_reinvestment,
                    scheme_name = excluded.scheme_name,
                    amc_name = coalesce(excluded.amc_name, master_mutual_funds.amc_name),
                    category = coalesce(excluded.category, master_mutual_funds.category),
                    nav = coalesce(excluded.nav, master_mutual_funds.nav),
                    nav_date = coalesce(excluded.nav_date, master_mutual_funds.nav_date),
                    status = excluded.status,
                    updated_at = excluded.updated_at
            """, batch)

    logger.info("Successfully synced %d AMFI mutual funds.", len(funds))
    return len(funds)
