"""
modules/ulips/ulip_collector.py
Orchestrates the ingestion, statutory date derivation, commercial enrichment,
and price analytics calculation for Life Insurers and ULIP funds.
Strictly dynamic: zero hardcoded funds or static entities.
"""

from datetime import datetime, timezone
from difflib import SequenceMatcher
import logging
import re
import sqlite3
from typing import Dict, Optional

from core.database import register_schema_documentation, transaction
from core.enums import InstrumentStatus, InsurerCategory
from core.schemas import SCHEMA_INSURERS, SCHEMA_ULIPS
from core.text_utils import clean_corporate_tokens, clean_english_text
from modules.ulips.analytics import update_ulip_price_analytics
from modules.ulips.commercial_plans import CommercialPlanScraper
from modules.ulips.irdai_entities import IRDAIEntityScraper
from modules.ulips.life_council import LifeCouncilScraper

logger = logging.getLogger(__name__)


def init_ulips_schema(conn: sqlite3.Connection):
    with transaction(conn) as cursor:
        cursor.execute("DROP TABLE IF EXISTS master_regulated_entities;")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS master_insurers (
                insurer_id TEXT PRIMARY KEY,
                insurer_name TEXT NOT NULL,
                reg_number TEXT,
                category TEXT NOT NULL DEFAULT 'LIFE_INSURERS',
                website TEXT,
                source_url TEXT,
                status TEXT NOT NULL DEFAULT 'ACTIVE',
                updated_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS master_ulip_funds (
                sfin TEXT PRIMARY KEY,
                fund_name TEXT NOT NULL,
                commercial_product_name TEXT,
                statutory_uin TEXT,
                inception_date TEXT,
                insurer_id TEXT NOT NULL,
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
        cursor.execute("PRAGMA table_info(master_ulip_funds)")
        existing = {col[1] for col in cursor.fetchall()}
        for col_name, col_type in [
            ("statutory_uin", "TEXT"),
            ("commercial_product_name", "TEXT"),
            ("inception_date", "TEXT"),
        ]:
            if col_name not in existing:
                cursor.execute(f"ALTER TABLE master_ulip_funds ADD COLUMN {col_name} {col_type}")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ulip_insurer ON master_ulip_funds(insurer_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ulip_date ON master_ulip_funds(nav_date)")
    register_schema_documentation(conn, "master_insurers", SCHEMA_INSURERS)
    register_schema_documentation(conn, "master_ulip_funds", SCHEMA_ULIPS)


def extract_inception_date_from_sfin(sfin: str) -> Optional[str]:
    """
    Extracts statutory IRDAI approval date directly from SFIN code:
    Format: ULI[Category][3-digit-insurer-reg][DDMMYY][FundName][3-digit-type]
    e.g. ULIF009310505BALICGRFND111 -> 2005-05-31
    """
    if not sfin or len(sfin) < 13:
        return None
    match = re.search(r"ULI[A-Z0-9]{4}(\d{2})(\d{2})(\d{2})", sfin.upper())
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


def match_insurer_id(raw_name: str, registry: Dict[str, str]) -> Optional[str]:
    clean_target = clean_corporate_tokens(raw_name)
    if clean_target in registry:
        return registry[clean_target]
    for norm_name, ins_id in registry.items():
        if norm_name in clean_target or clean_target in norm_name:
            return ins_id
    best_id, best_score = None, 0.0
    for norm_name, ins_id in registry.items():
        score = SequenceMatcher(None, clean_target, norm_name).ratio()
        if score > best_score and score >= 0.65:
            best_score, best_id = score, ins_id
    return best_id


def enrich_commercial_plans(conn: sqlite3.Connection):
    logger.info("Enriching commercial product names & statutory UINs from IRDAI...")
    commercial_scraper = CommercialPlanScraper()
    catalog = commercial_scraper.fetch_irdai_product_catalog()
    if not catalog:
        logger.info("IRDAI product workbooks not available; skipping enrichment.")
        return

    cursor = conn.cursor()
    cursor.execute("SELECT insurer_id, reg_number FROM master_insurers WHERE reg_number IS NOT NULL")
    reg_to_ins = {r[1].zfill(3): r[0] for r in cursor.fetchall()}

    cursor.execute("SELECT sfin, fund_name, insurer_id FROM master_ulip_funds")
    funds = cursor.fetchall()
    updates = []

    for sfin, fund_name, ins_id in funds:
        ins_code = next((reg for reg, iid in reg_to_ins.items() if iid == ins_id), None)
        if not ins_code or ins_code not in catalog:
            continue
        best_match, best_score = None, 0.0
        for uin, prod_name in catalog[ins_code]:
            score = SequenceMatcher(None, clean_corporate_tokens(fund_name), clean_corporate_tokens(prod_name)).ratio()
            if score > best_score and score >= 0.45:
                best_score, best_match = score, (prod_name, uin)
        if best_match:
            updates.append((best_match[0], best_match[1], sfin))

    if updates:
        with transaction(conn) as cur:
            cur.executemany("""
                UPDATE master_ulip_funds
                SET commercial_product_name = coalesce(?, commercial_product_name),
                    statutory_uin = coalesce(?, statutory_uin)
                WHERE sfin = ?
            """, updates)
    logger.info("Enriched %d funds with commercial plan metadata.", len(updates))


def sync_insurers_ulips(conn: sqlite3.Connection) -> int:
    init_ulips_schema(conn)
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")

    # 1. Sync official Life Insurers
    irdai_scraper = IRDAIEntityScraper()
    ins_rows = []
    for item in irdai_scraper.scrape_life_insurers():
        reg = item["reg_number"] or "0"
        name = clean_english_text(item["insurer_name"])
        ins_rows.append((
            f"INS_{reg}", name, reg, InsurerCategory.LIFE_INSURERS.value,
            item["website"], item["source_url"], InstrumentStatus.ACTIVE.value, now_iso
        ))

    if ins_rows:
        with transaction(conn) as cursor:
            cursor.executemany("""
                INSERT INTO master_insurers (
                    insurer_id, insurer_name, reg_number, category, website, source_url, status, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(insurer_id) DO UPDATE SET
                    insurer_name = excluded.insurer_name,
                    reg_number = excluded.reg_number,
                    category = excluded.category,
                    website = coalesce(nullif(excluded.website, ''), master_insurers.website),
                    source_url = excluded.source_url,
                    updated_at = excluded.updated_at
            """, ins_rows)

    # 2. Sync Life Council ULIP funds
    cursor = conn.cursor()
    cursor.execute("SELECT insurer_id, insurer_name FROM master_insurers")
    registry = {clean_corporate_tokens(name): ins_id for ins_id, name in cursor.fetchall()}

    life_scraper = LifeCouncilScraper()
    ulip_batch = []
    hist_batch = []
    funds_count = 0

    for fund in life_scraper.scrape_all_funds():
        ins_id = match_insurer_id(fund["insurer_name_raw"], registry)
        if not ins_id:
            continue

        sfin = fund["sfin"]
        nav = fund["latest_nav"]
        nav_date = fund["nav_date"]
        inception_date = extract_inception_date_from_sfin(sfin)

        ulip_batch.append((
            sfin, clean_english_text(fund["fund_name"]), inception_date,
            ins_id, nav, nav_date, fund["status"], now_iso
        ))
        if nav and nav_date:
            hist_batch.append((sfin, nav_date, nav, now_iso))

        if len(ulip_batch) >= 100:
            with transaction(conn) as cur:
                cur.executemany("""
                    INSERT INTO master_ulip_funds (
                        sfin, fund_name, inception_date, insurer_id, latest_nav, nav_date, status, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(sfin) DO UPDATE SET
                        fund_name = excluded.fund_name,
                        inception_date = coalesce(excluded.inception_date, master_ulip_funds.inception_date),
                        insurer_id = excluded.insurer_id,
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
                    sfin, fund_name, inception_date, insurer_id, latest_nav, nav_date, status, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sfin) DO UPDATE SET
                    fund_name = excluded.fund_name,
                    inception_date = coalesce(excluded.inception_date, master_ulip_funds.inception_date),
                    insurer_id = excluded.insurer_id,
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

    # 3. Commercial product enrichment & trailing price analytics
    enrich_commercial_plans(conn)
    update_ulip_price_analytics(conn)

    logger.info("Successfully synced %d ULIP funds.", funds_count)
    return funds_count
