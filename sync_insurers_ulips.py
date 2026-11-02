"""
sync_insurers_ulips.py
"""

import logging
import re
import sqlite3
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, Optional

from scrapers.irdai_scraper import IRDAIScraper
from scrapers.life_council_scraper import LifeCouncilScraper
from scrapers.commercial_plan_scraper import CommercialPlanScraper

DB_PATH = Path("data/master_insurers_ulips.sqlite")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

STOPWORDS = {
    "company", "co", "limited", "ltd", "pvt", "private",
    "corporation", "corp", "insurance", "life", "of", "india",
    "services", "ins", "general", "assurance"
}

def is_devanagari(text: str) -> bool:
    """Checks if a string contains Hindi/Devanagari characters."""
    return bool(re.search(r"[\u0900-\u097F]", text))

def clean_corporate_name(text: str) -> str:
    if not text:
        return ""
    if re.search(r"\blife\s+insurance\s+corporation\b|\blic\b", text, re.I):
        return "lic"
    text = re.sub(r"\(.*?\)", " ", text.lower())
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    tokens = sorted([t for t in text.split() if t not in STOPWORDS and len(t) > 1])
    return " ".join(tokens)

def match_insurer_id(scraped_name: str, insurer_registry: Dict[str, str]) -> Optional[str]:
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

def init_database_schema(conn: sqlite3.Connection):
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS master_regulated_entities (
            entity_id TEXT PRIMARY KEY,
            category TEXT,
            entity_name TEXT,
            reg_number TEXT,
            source_url TEXT,
            status TEXT DEFAULT 'ACTIVE',
            updated_at TEXT,
            website TEXT
        )
    """)

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

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_reg_ent_cat ON master_regulated_entities(category)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ulip_insurer ON master_ulip_funds(insurer_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ulip_nav_date ON master_ulip_funds(nav_date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ulip_hist_sfin ON ulip_nav_history(sfin)")
    conn.commit()

def enrich_commercial_names(conn: sqlite3.Connection):
    """
    Enriches master_ulip_funds with commercial product names and statutory UINs
    streamed dynamically from IRDAI registries. Zero hardcoded assets.
    """
    cursor = conn.cursor()
    commercial_scraper = CommercialPlanScraper()
    irdai_catalog = commercial_scraper.fetch_irdai_product_catalog()

    cursor.execute("SELECT sfin, fund_name FROM master_ulip_funds")
    all_funds = cursor.fetchall()
    logger.info(f"Resolving commercial product names for {len(all_funds)} statutory funds...")

    updates = []
    delimiters = re.compile(r"\s+-\s+|\s+–\s+|\s+:\s+")

    for sfin, fund_name in all_funds:
        ins_code = sfin[-3:]
        products = irdai_catalog.get(ins_code, [])

        matched = commercial_scraper.resolve_best_product(sfin, fund_name, products)
        if matched:
            uin, prod_name = matched
            updates.append((prod_name, uin, sfin))
        else:
            # Fallback to normalized product family from fund name if not in IRDAI registry
            parts = delimiters.split(fund_name)
            candidate = parts[0].strip() if len(parts) > 1 and len(parts[0].strip()) > 3 else fund_name.strip()
            updates.append((candidate, None, sfin))

    cursor.executemany("""
        UPDATE master_ulip_funds
        SET commercial_product_name = ?,
            uin = coalesce(?, uin)
        WHERE sfin = ?
    """, updates)

    conn.commit()
    logger.info(f"Commercial product enrichment complete for {len(updates)} funds.")
    
def compute_and_update_price_analytics(conn: sqlite3.Connection):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT sfin, MAX(nav), MIN(nav), AVG(nav)
        FROM ulip_nav_history
        WHERE nav IS NOT NULL AND nav > 0
        GROUP BY sfin
    """)
    stats_rows = cursor.fetchall()

    if stats_rows:
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

def sync_all():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    init_database_schema(conn)
    cursor = conn.cursor()
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")

    # 1. DYNAMIC IRDAI DISCOVERY & SYNC
    irdai_scraper = IRDAIScraper()

    upsert_ent_sql = """
        INSERT INTO master_regulated_entities (
            entity_id, category, entity_name, reg_number, source_url, status, updated_at, website
        ) VALUES (?, ?, ?, ?, ?, 'ACTIVE', ?, ?)
        ON CONFLICT(entity_id) DO UPDATE SET
            category = excluded.category,
            entity_name = CASE 
                WHEN ? AND NOT ? THEN master_regulated_entities.entity_name 
                ELSE excluded.entity_name 
            END,
            reg_number = excluded.reg_number,
            source_url = excluded.source_url,
            updated_at = excluded.updated_at,
            website = coalesce(nullif(excluded.website, ''), master_regulated_entities.website)
    """

    upsert_ins_sql = """
        INSERT INTO master_insurers (
            insurer_id, insurer_name, reg_number, category, website, source_url, status, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'ACTIVE', ?)
        ON CONFLICT(insurer_id) DO UPDATE SET
            insurer_name = CASE 
                WHEN ? AND NOT ? THEN master_insurers.insurer_name 
                ELSE excluded.insurer_name 
            END,
            reg_number = excluded.reg_number,
            website = coalesce(nullif(excluded.website, ''), master_insurers.website),
            source_url = excluded.source_url,
            updated_at = excluded.updated_at
    """

    ent_count = 0
    ins_count = 0
    logger.info("Executing dynamic IRDAI entity crawl...")

    for item in irdai_scraper.scrape_all():
        reg = item["reg_number"] or str(ent_count + 1)
        cat = item["category"]
        name = item["entity_name"]
        entity_id = f"ENT_{reg}" if reg.isdigit() else f"ENT_{cat}_{reg}"
        is_dev = is_devanagari(name)

        cursor.execute(upsert_ent_sql, (
            entity_id, cat, name, reg, item["source_url"], now_iso, item["website"],
            is_dev, False
        ))
        ent_count += 1

        if "LIFE" in cat and "NON_LIFE" not in cat:
            ins_id = f"INS_{reg}"
            cursor.execute(upsert_ins_sql, (
                ins_id, name, reg, cat, item["website"], item["source_url"], now_iso,
                is_dev, False
            ))
            ins_count += 1

    conn.commit()
    logger.info(f"IRDAI Ingest Complete: {ent_count} entities and {ins_count} life insurers.")

    # 2. DYNAMIC LIFE COUNCIL SCRAPE
    cursor.execute("SELECT insurer_id, insurer_name FROM master_insurers")
    raw_insurers = cursor.fetchall()
    insurer_registry: Dict[str, str] = {
        clean_corporate_name(name): ins_id for ins_id, name in raw_insurers
    }
    logger.info(f"Loaded {len(insurer_registry)} statutory life insurers for mapping.")

    life_scraper = LifeCouncilScraper()
    upsert_ulip_sql = """
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

    insert_hist_sql = """
        INSERT OR IGNORE INTO ulip_nav_history (sfin, nav_date, nav, created_at)
        VALUES (?, ?, ?, ?)
    """

    ulip_batch = []
    hist_batch = []
    funds_count = 0

    for fund in life_scraper.scrape_all_funds():
        ins_raw = fund["insurer_name_raw"]
        ins_id = match_insurer_id(ins_raw, insurer_registry)

        if not ins_id:
            logger.warning(f"Could not map insurer '{ins_raw}' to master_insurers. Skipping SFIN {fund['sfin']}.")
            continue

        sfin = fund["sfin"]
        nav = fund["latest_nav"]
        nav_date = fund["nav_date"]

        ulip_batch.append((
            sfin, fund["fund_name"], fund["inception_date"], ins_id, nav, nav_date, fund["status"], now_iso
        ))
        if nav and nav_date:
            hist_batch.append((sfin, nav_date, nav, now_iso))

        if len(ulip_batch) >= 100:
            cursor.executemany(upsert_ulip_sql, ulip_batch)
            cursor.executemany(insert_hist_sql, hist_batch)
            conn.commit()
            funds_count += len(ulip_batch)
            ulip_batch.clear()
            hist_batch.clear()

    if ulip_batch:
        cursor.executemany(upsert_ulip_sql, ulip_batch)
        cursor.executemany(insert_hist_sql, hist_batch)
        conn.commit()
        funds_count += len(ulip_batch)

    # 3. ENRICHMENT & METRICS
    enrich_commercial_names(conn)
    compute_and_update_price_analytics(conn)

    cursor.execute("SELECT COUNT(*), COUNT(commercial_product_name), COUNT(nav_avg) FROM master_ulip_funds")
    total_funds, with_commercial, with_stats = cursor.fetchone()
    logger.info(
        f"ULIP Pipeline Complete. Funds Ingested: {total_funds} | "
        f"Commercial Plans Mapped: {with_commercial} | Analytics Populated: {with_stats}"
    )

    conn.close()

if __name__ == "__main__":
    sync_all()