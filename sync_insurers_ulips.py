"""
sync_insurers_ulips.py

Syncs Life Insurers and ULIP Funds into data/master_insurers_ulips.sqlite.
Maintains historical time-series pricing, computes price statistics (High, Low, Avg),
and enriches funds with commercial umbrella product names and UIN codes.
Auto-creates database directories and tables if they do not exist.
"""

import logging
import re
import sqlite3
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, Optional

from scrapers.life_council_scraper import LifeCouncilScraper
from scrapers.commercial_plan_scraper import CommercialPlanScraper

DB_PATH = Path("data/master_insurers_ulips.sqlite")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

STOPWORDS = {
    "company", "co", "limited", "ltd", "pvt", "private",
    "corporation", "corp", "insurance", "life", "of", "india",
    "services", "ins", "general", "assurance",
}


def clean_corporate_name(text: str) -> str:
    """Standardizes insurer corporate names for resilient token comparison."""
    if not text:
        return ""

    if re.search(r"\blife\s+insurance\s+corporation\b|\blic\b", text, re.I):
        return "lic"

    text = re.sub(r"\(.*?\)", " ", text.lower())
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    tokens = sorted([t for t in text.split() if t not in STOPWORDS and len(t) > 1])
    return " ".join(tokens)


def match_insurer_id(scraped_name: str, insurer_registry: Dict[str, str]) -> Optional[str]:
    """Matches scraped portal names to statutory master_insurers.insurer_id."""
    clean_target = clean_corporate_name(scraped_name)
    if not clean_target:
        return None

    if clean_target in insurer_registry:
        return insurer_registry[clean_target]

    target_tokens = set(clean_target.split())
    best_id = None
    best_overlap = 0.0

    for norm_name, ins_id in insurer_registry.items():
        if not norm_name:
            continue
        reg_tokens = set(norm_name.split())

        if reg_tokens.issubset(target_tokens) or target_tokens.issubset(reg_tokens):
            return ins_id

        intersection = target_tokens.intersection(reg_tokens)
        union = target_tokens.union(reg_tokens)
        overlap = len(intersection) / len(union) if union else 0.0

        if overlap > best_overlap:
            best_overlap = overlap
            best_id = ins_id

    if best_overlap >= 0.50:
        return best_id

    best_score = 0.0
    for norm_name, ins_id in insurer_registry.items():
        score = SequenceMatcher(None, clean_target, norm_name).ratio()
        if score > best_score:
            best_score = score
            best_id = ins_id

    return best_id if best_score >= 0.60 else None


def ensure_schema(conn: sqlite3.Connection):
    """Establishes tables and schema migrations for ULIP funds and analytics."""
    cursor = conn.cursor()

    # Ensure parent table exists so foreign keys do not fail
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS master_insurers (
            insurer_id TEXT PRIMARY KEY,
            insurer_name TEXT NOT NULL,
            reg_number TEXT,
            category TEXT DEFAULT 'LIST_OF_LIFE_INSURERS',
            website TEXT,
            source_url TEXT,
            status TEXT DEFAULT 'ACTIVE',
            updated_at TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS master_ulip_funds (
            sfin TEXT PRIMARY KEY,
            fund_name TEXT,
            commercial_product_name TEXT,
            uin TEXT,
            inception_date TEXT,
            insurer_id TEXT NOT NULL,
            latest_nav REAL,
            nav_date TEXT,
            nav_52w_high REAL,
            nav_52w_low REAL,
            nav_all_time_high REAL,
            nav_all_time_low REAL,
            nav_avg REAL,
            status TEXT,
            updated_at TEXT,
            FOREIGN KEY (insurer_id) REFERENCES master_insurers(insurer_id)
        )
    """)

    # Historical NAV time-series log
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ulip_nav_history (
            sfin TEXT NOT NULL,
            nav_date TEXT NOT NULL,
            nav REAL NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (sfin, nav_date),
            FOREIGN KEY (sfin) REFERENCES master_ulip_funds(sfin)
        )
    """)

    # Dynamic column migrations if table already existed
    cursor.execute("PRAGMA table_info(master_ulip_funds)")
    existing_cols = {row[1] for row in cursor.fetchall()}
    columns_to_verify = [
        ("commercial_product_name", "TEXT"),
        ("uin", "TEXT"),
        ("nav_52w_high", "REAL"),
        ("nav_52w_low", "REAL"),
        ("nav_all_time_high", "REAL"),
        ("nav_all_time_low", "REAL"),
        ("nav_avg", "REAL"),
    ]
    for col_name, col_type in columns_to_verify:
        if col_name not in existing_cols:
            cursor.execute(f"ALTER TABLE master_ulip_funds ADD COLUMN {col_name} {col_type}")

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ulip_insurer ON master_ulip_funds(insurer_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ulip_nav_date ON master_ulip_funds(nav_date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ulip_hist_sfin ON ulip_nav_history(sfin)")
    conn.commit()


def compute_and_update_price_analytics(conn: sqlite3.Connection):
    """Calculates High, Low, and Average prices from historical observations."""
    cursor = conn.cursor()

    cursor.execute("""
        SELECT 
            sfin,
            MAX(nav) AS max_nav,
            MIN(nav) AS min_nav,
            AVG(nav) AS mean_nav
        FROM ulip_nav_history
        WHERE nav IS NOT NULL AND nav > 0
        GROUP BY sfin
    """)
    stats_rows = cursor.fetchall()

    if stats_rows:
        logger.info(f"Computing historical price metrics for {len(stats_rows)} funds...")
        cursor.executemany("""
            UPDATE master_ulip_funds
            SET nav_all_time_high = round(?, 4),
                nav_all_time_low = round(?, 4),
                nav_avg = round(?, 4),
                nav_52w_high = round(?, 4),
                nav_52w_low = round(?, 4)
            WHERE sfin = ?
        """, [(r[1], r[2], r[3], r[1], r[2], r[0]) for r in stats_rows])
    else:
        cursor.execute("""
            UPDATE master_ulip_funds
            SET nav_all_time_high = latest_nav,
                nav_all_time_low = latest_nav,
                nav_avg = latest_nav,
                nav_52w_high = latest_nav,
                nav_52w_low = latest_nav
            WHERE latest_nav IS NOT NULL AND nav_avg IS NULL
        """)

    conn.commit()


def enrich_commercial_names(conn: sqlite3.Connection):
    """Enriches funds with commercial umbrella names and IRDAI UINs."""
    cursor = conn.cursor()
    commercial_scraper = CommercialPlanScraper()
    mappings = commercial_scraper.fetch_dynamic_insurer_mappings()

    logger.info(f"Applying commercial product mappings ({len(mappings)} entries)...")
    for item in mappings:
        sfin = item.get("sfin")
        prod_name = item.get("product_name")
        uin = item.get("uin")

        if sfin and prod_name:
            cursor.execute("""
                UPDATE master_ulip_funds
                SET commercial_product_name = CASE 
                        WHEN commercial_product_name IS NULL OR commercial_product_name = '' THEN ?
                        WHEN instr(commercial_product_name, ?) > 0 THEN commercial_product_name
                        ELSE commercial_product_name || ' / ' || ?
                    END,
                    uin = coalesce(uin, ?)
                WHERE sfin = ?
            """, (prod_name, prod_name, prod_name, uin, sfin))

    conn.commit()


def sync_ulip_funds():
    # 1. Automatically create parent directory if it does not exist
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    # 2. Connect and automatically initialize schema if file is created fresh
    conn = sqlite3.connect(DB_PATH)
    ensure_schema(conn)
    cursor = conn.cursor()

    # 3. If master_insurers is empty, seed it via sync_irdai if present
    cursor.execute("SELECT COUNT(*) FROM master_insurers")
    if cursor.fetchone()[0] == 0:
        logger.info("master_insurers table is empty. Attempting statutory insurer initialization...")
        try:
            from sync_irdai import sync_insurers
            sync_insurers(conn)
        except ImportError:
            logger.warning("sync_irdai not found; proceeding with existing schema.")

    cursor.execute("SELECT insurer_id, insurer_name FROM master_insurers")
    raw_insurers = cursor.fetchall()
    insurer_registry: Dict[str, str] = {
        clean_corporate_name(name): ins_id for ins_id, name in raw_insurers
    }

    scraper = LifeCouncilScraper()
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")

    upsert_fund_sql = """
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
    """

    insert_history_sql = """
        INSERT OR IGNORE INTO ulip_nav_history (sfin, nav_date, nav, created_at)
        VALUES (?, ?, ?, ?)
    """

    records_batch = []
    history_batch = []
    total_processed = 0

    for fund in scraper.scrape_all_funds():
        ins_name_raw = fund["insurer_name_raw"]
        ins_id = match_insurer_id(ins_name_raw, insurer_registry)

        if not ins_id:
            logger.warning(
                f"Could not map insurer '{ins_name_raw}' to master_insurers. Skipping SFIN {fund['sfin']}."
            )
            continue

        sfin = fund["sfin"]
        nav = fund["latest_nav"]
        nav_date = fund["nav_date"]

        records_batch.append((
            sfin,
            fund["fund_name"],
            fund["inception_date"],
            ins_id,
            nav,
            nav_date,
            fund["status"],
            now_iso,
        ))

        if nav and nav_date:
            history_batch.append((sfin, nav_date, nav, now_iso))

        if len(records_batch) >= 100:
            cursor.executemany(upsert_fund_sql, records_batch)
            cursor.executemany(insert_history_sql, history_batch)
            conn.commit()
            total_processed += len(records_batch)
            records_batch.clear()
            history_batch.clear()

    if records_batch:
        cursor.executemany(upsert_fund_sql, records_batch)
        cursor.executemany(insert_history_sql, history_batch)
        conn.commit()
        total_processed += len(records_batch)

    # Enrich with commercial names & calculate price stats
    enrich_commercial_names(conn)
    compute_and_update_price_analytics(conn)

    cursor.execute("""
        SELECT 
            COUNT(*), 
            COUNT(commercial_product_name), 
            COUNT(nav_avg)
        FROM master_ulip_funds
    """)
    total_funds, with_commercial, with_stats = cursor.fetchone()

    logger.info(
        f"ULIP Sync complete. Processed: {total_funds} funds | "
        f"Commercial Plans Mapped: {with_commercial} | Analytics Populated: {with_stats}"
    )

    conn.close()


if __name__ == "__main__":
    sync_ulip_funds()