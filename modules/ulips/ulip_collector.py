"""
modules/ulips/ulip_collector.py
Orchestrates the ingestion, statutory date derivation, company mapping,
Artos-standard classification, and price analytics calculation for Life Insurers and ULIP funds.
Strictly dynamic: zero hardcoded funds, zero synthetic fuzzy matching.
"""

from datetime import datetime, timezone
import logging
import re
import sqlite3
from typing import Dict, Optional, Tuple

from core.constants import (
    SFIN_DATE_PATTERN,
    ULIP_BALANCED_PATTERNS,
    ULIP_DEBT_PATTERNS,
    ULIP_DISCONTINUED_PATTERNS,
    ULIP_EQUITY_PATTERNS,
    ULIP_MONEY_MARKET_PATTERNS,
    ULIP_PENSION_PATTERNS,
)
from core.database import register_schema_documentation, transaction
from core.enums import InstrumentStatus, InsurerCategory, UlipCategory, UlipFundType
from core.schemas import SCHEMA_INSURERS, SCHEMA_ULIPS
from core.text_utils import clean_corporate_tokens, clean_english_text
from modules.ulips.analytics import update_ulip_price_analytics
from modules.ulips.irdai_entities import IRDAIEntityScraper
from modules.ulips.life_council import LifeCouncilScraper

logger = logging.getLogger(__name__)


def format_ulip_search_name(insurer_name: str, fund_name: str) -> str:
    """
    Builds a canonical, search-friendly display title for the ULIP fund (e.g. 'SBI Life - Equity Fund').
    Ensures client apps searching for the insurer name or fund title match seamlessly.
    """
    clean_fund = clean_english_text(fund_name).strip()
    if clean_fund.isupper():
        clean_fund = clean_fund.title()
    brand = insurer_name or ""
    for suffix in (
        " Insurance Company Limited", " Insurance Co. Ltd.", " Life Insurance Limited",
        " Life Insurance Company Limited", " Company Limited", " Insurance Limited",
        " Corporation of India", " Co Ltd", " Limited", " Ltd"
    ):
        if suffix in brand:
            brand = brand.replace(suffix, "")
            break
    brand = brand.strip()
    if "Life Insurance Corporation" in (insurer_name or ""):
        brand = "LIC"

    if not brand:
        return clean_fund
    if clean_fund.lower().startswith(brand.lower()):
        return clean_fund
    return f"{brand} - {clean_fund}"


def init_ulips_schema(conn: sqlite3.Connection):
    """
    Initializes database schema for Life Insurers and ULIP Segregated Funds.
    Automatically handles schema evolution and documentation registration.
    """
    with transaction(conn) as cursor:
        cursor.execute("DROP TABLE IF EXISTS master_regulated_entities;")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS master_insurers (
                insurer_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                insurer_name TEXT NOT NULL,
                reg_number TEXT,
                category TEXT NOT NULL DEFAULT 'LIFE_INSURERS',
                website TEXT,
                source_url TEXT,
                status TEXT NOT NULL DEFAULT 'ACTIVE',
                updated_at TEXT NOT NULL
            )
        """)

        # Drop legacy master_ulip_funds if it contains obsolete unverified columns or lacks name
        cursor.execute("PRAGMA table_info(master_ulip_funds)")
        existing = {col[1] for col in cursor.fetchall()}
        if existing and ("commercial_product_name" in existing or "statutory_uin" in existing or "category" not in existing or "name" not in existing):
            cursor.execute("DROP TABLE master_ulip_funds;")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS master_ulip_funds (
                sfin TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                fund_name TEXT NOT NULL,
                insurer_id TEXT NOT NULL,
                insurer_name TEXT NOT NULL,
                category TEXT NOT NULL,
                fund_type TEXT NOT NULL,
                inception_date TEXT,
                latest_nav REAL,
                nav_date TEXT,
                nav_all_time_high REAL,
                nav_all_time_low REAL,
                nav_avg REAL,
                nav_52w_high REAL,
                nav_52w_low REAL,
                status TEXT NOT NULL DEFAULT 'ACTIVE',
                updated_at TEXT NOT NULL,
                FOREIGN KEY (insurer_id) REFERENCES master_insurers(insurer_id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ulip_nav_history (
                sfin TEXT NOT NULL,
                nav_date TEXT NOT NULL,
                nav REAL NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (sfin, nav_date)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ulip_name ON master_ulip_funds(name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ulip_insurer ON master_ulip_funds(insurer_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ulip_category ON master_ulip_funds(category)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ulip_fund_type ON master_ulip_funds(fund_type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ulip_date ON master_ulip_funds(nav_date)")

    register_schema_documentation(conn, "master_insurers", SCHEMA_INSURERS)
    register_schema_documentation(conn, "master_ulip_funds", SCHEMA_ULIPS)


def extract_inception_date_from_sfin(sfin: str) -> Optional[str]:
    """
    Extracts statutory IRDAI approval date directly from SFIN code:
    Format: ULI/ULG[Category][3-digit-insurer-reg][DDMMYY][FundName][3-digit-type]
    e.g. ULIF009310505BALICGRFND111 -> 2005-05-31
    """
    if not sfin or len(sfin) < 10:
        return None
    cleaned = re.sub(r"[^A-Z0-9]", "", sfin.upper())
    match = SFIN_DATE_PATTERN.search(cleaned)
    if match:
        day, month, year_2d = match.groups()
        try:
            d, m = int(day), int(month)
            if 1 <= d <= 31 and 1 <= m <= 12:
                yy = int(year_2d)
                full_year = 2000 + yy if yy <= 50 else 1900 + yy
                return f"{full_year:04d}-{m:02d}-{d:02d}"
        except ValueError:
            pass
    return None


def classify_ulip_fund(sfin: str, fund_name: str) -> Tuple[str, str]:
    """
    Statutorily classifies ULIP funds into Category and Fund Type (Artos standard).
    Zero guessing: strictly derived from IRDAI SFIN nomenclature and statutory fund titles.
    Returns: (category, fund_type)
    """
    sfin_clean = (sfin or "").strip().upper()
    name_clean = (fund_name or "").strip()
    combined = f"{sfin_clean} {name_clean}".lower()

    # 1. Determine Fund Type (INDIVIDUAL vs GROUP vs DISCONTINUED)
    if sfin_clean.startswith(("DPF", "UNCL")) or any(pat in combined for pat in ULIP_DISCONTINUED_PATTERNS):
        fund_type = UlipFundType.DISCONTINUED.value
    elif sfin_clean.startswith(("ULGF", "ULGB")) or re.search(r"\bgroup\b", combined):
        fund_type = UlipFundType.GROUP.value
    else:
        fund_type = UlipFundType.INDIVIDUAL.value

    # 2. Determine Asset Category
    if fund_type == UlipFundType.DISCONTINUED.value or any(pat in combined for pat in ULIP_DISCONTINUED_PATTERNS):
        category = UlipCategory.DISCONTINUED.value
    elif any(pat in combined for pat in ULIP_PENSION_PATTERNS):
        category = UlipCategory.PENSION.value
    elif any(pat in combined for pat in ULIP_MONEY_MARKET_PATTERNS):
        category = UlipCategory.MONEY_MARKET.value
    elif any(pat in combined for pat in ULIP_BALANCED_PATTERNS):
        category = UlipCategory.BALANCED.value
    elif any(pat in combined for pat in ULIP_EQUITY_PATTERNS):
        category = UlipCategory.EQUITY.value
    elif any(pat in combined for pat in ULIP_DEBT_PATTERNS):
        category = UlipCategory.DEBT.value
    else:
        category = UlipCategory.OTHER.value

    return category, fund_type


def match_insurer_id(raw_name: str, registry: Dict[str, str]) -> Optional[str]:
    """
    Matches raw company name from life council feed to master insurer ID via exact corporate token normalization.
    Zero fuzzy matching: purely deterministic exact match or normalized subset match.
    """
    clean_target = clean_corporate_tokens(raw_name)
    if clean_target in registry:
        return registry[clean_target]
    for norm_name, ins_id in registry.items():
        if norm_name in clean_target or clean_target in norm_name:
            return ins_id
    return None


def sync_insurers_ulips(conn: sqlite3.Connection) -> int:
    """
    Coordinates end-to-end ingestion of IRDAI Life Insurers and Life Insurance Council ULIPs.
    Maps every fund directly to its official source company, formatted search name, and asset category.
    """
    init_ulips_schema(conn)
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")

    # 1. Sync official Life Insurers from IRDAI
    irdai_scraper = IRDAIEntityScraper()
    ins_rows = []
    for item in irdai_scraper.scrape_life_insurers():
        reg = item["reg_number"] or "0"
        name = clean_english_text(item["insurer_name"])
        ins_rows.append((
            f"INS_{reg}", name, name, reg, InsurerCategory.LIFE_INSURERS.value,
            item["website"], item["source_url"], InstrumentStatus.ACTIVE.value, now_iso
        ))

    if ins_rows:
        with transaction(conn) as cursor:
            cursor.executemany("""
                INSERT INTO master_insurers (
                    insurer_id, name, insurer_name, reg_number, category, website, source_url, status, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(insurer_id) DO UPDATE SET
                    name = excluded.name,
                    insurer_name = excluded.insurer_name,
                    reg_number = excluded.reg_number,
                    category = excluded.category,
                    website = coalesce(nullif(excluded.website, ''), master_insurers.website),
                    source_url = excluded.source_url,
                    updated_at = excluded.updated_at
            """, ins_rows)

    # 2. Build insurer registries from master_insurers
    cursor = conn.cursor()
    cursor.execute("SELECT insurer_id, insurer_name, reg_number FROM master_insurers")
    all_insurers = cursor.fetchall()

    registry_name: Dict[str, Tuple[str, str]] = {
        clean_corporate_tokens(row["insurer_name"]): (row["insurer_id"], row["insurer_name"])
        for row in all_insurers
    }
    registry_reg: Dict[str, Tuple[str, str]] = {
        str(row["reg_number"]).strip().zfill(3): (row["insurer_id"], row["insurer_name"])
        for row in all_insurers
        if row["reg_number"]
    }
    registry_id: Dict[str, Tuple[str, str]] = {
        row["insurer_id"]: (row["insurer_id"], row["insurer_name"])
        for row in all_insurers
    }

    # 3. Ingest Life Council ULIP funds
    life_scraper = LifeCouncilScraper()
    ulip_batch = []
    hist_batch = []
    funds_count = 0

    for fund in life_scraper.scrape_all_funds():
        sfin = (fund.get("sfin") or "").strip().upper()
        if not sfin:
            continue

        # Insurer resolution:
        # Step A: Match via SFIN suffix (last 3 digits are IRDAI insurer reg_number)
        reg_candidate = sfin[-3:] if len(sfin) >= 3 and sfin[-3:].isdigit() else None
        ins_tuple = registry_reg.get(reg_candidate)

        # Step B: Match via raw insurer name
        if not ins_tuple and fund.get("insurer_name_raw"):
            ins_id = match_insurer_id(fund["insurer_name_raw"], {k: v[0] for k, v in registry_name.items()})
            if ins_id:
                ins_tuple = registry_id.get(ins_id)

        if not ins_tuple:
            logger.warning("Could not resolve insurer for fund SFIN: %s", sfin)
            continue

        insurer_id, insurer_name = ins_tuple
        clean_name = clean_english_text(fund["fund_name"])
        search_name = format_ulip_search_name(insurer_name, clean_name)
        category, fund_type = classify_ulip_fund(sfin, clean_name)
        inception_date = extract_inception_date_from_sfin(sfin)
        nav = fund.get("latest_nav")
        nav_date = fund.get("nav_date")

        ulip_batch.append((
            sfin, search_name, clean_name, insurer_id, insurer_name, category, fund_type,
            inception_date, nav, nav_date, fund.get("status", InstrumentStatus.ACTIVE.value), now_iso
        ))
        if nav and nav_date:
            hist_batch.append((sfin, nav_date, nav, now_iso))

        if len(ulip_batch) >= 100:
            with transaction(conn) as cur:
                cur.executemany("""
                    INSERT INTO master_ulip_funds (
                        sfin, name, fund_name, insurer_id, insurer_name, category, fund_type,
                        inception_date, latest_nav, nav_date, status, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(sfin) DO UPDATE SET
                        name = excluded.name,
                        fund_name = excluded.fund_name,
                        insurer_id = excluded.insurer_id,
                        insurer_name = excluded.insurer_name,
                        category = excluded.category,
                        fund_type = excluded.fund_type,
                        inception_date = coalesce(excluded.inception_date, master_ulip_funds.inception_date),
                        latest_nav = excluded.latest_nav,
                        nav_date = excluded.nav_date,
                        status = excluded.status,
                        updated_at = excluded.updated_at
                """, ulip_batch)
                cur.executemany("""
                    INSERT OR IGNORE INTO ulip_nav_history (sfin, nav_date, nav, created_at)
                    VALUES (?, ?, ?, ?)
                """, hist_batch)
            funds_count += len(ulip_batch)
            ulip_batch.clear()
            hist_batch.clear()

    if ulip_batch:
        with transaction(conn) as cur:
            cur.executemany("""
                INSERT INTO master_ulip_funds (
                    sfin, name, fund_name, insurer_id, insurer_name, category, fund_type,
                    inception_date, latest_nav, nav_date, status, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sfin) DO UPDATE SET
                    name = excluded.name,
                    fund_name = excluded.fund_name,
                    insurer_id = excluded.insurer_id,
                    insurer_name = excluded.insurer_name,
                    category = excluded.category,
                    fund_type = excluded.fund_type,
                    inception_date = coalesce(excluded.inception_date, master_ulip_funds.inception_date),
                    latest_nav = excluded.latest_nav,
                    nav_date = excluded.nav_date,
                    status = excluded.status,
                    updated_at = excluded.updated_at
            """, ulip_batch)
            cur.executemany("""
                INSERT OR IGNORE INTO ulip_nav_history (sfin, nav_date, nav, created_at)
                VALUES (?, ?, ?, ?)
            """, hist_batch)
        funds_count += len(ulip_batch)

    # 4. Trailing price analytics calculation
    update_ulip_price_analytics(conn)

    logger.info("Successfully synced %d ULIP funds with source company and category mappings.", funds_count)
    return funds_count
