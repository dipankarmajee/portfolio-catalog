"""
modules/insurance/insurance_collector.py
Orchestrates IRDAI life insurance product ingestion into SQLite database.
"""
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict

from core.database import register_schema_documentation, transaction
from core.schemas import SCHEMA_INSURANCE_PRODUCTS
from core.text_utils import clean_english_text
from modules.insurance.irdai_products_scraper import IRDAIProductsScraper

logger = logging.getLogger(__name__)


def init_insurance_schema(conn: sqlite3.Connection):
    """Creates master_insurance_products table if not exists."""
    with transaction(conn) as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS master_insurance_products (
                uin TEXT PRIMARY KEY,
                product_name TEXT NOT NULL,
                name TEXT NOT NULL,
                insurer_name TEXT NOT NULL,
                category TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'ACTIVE',
                launch_date TEXT,
                updated_at TEXT NOT NULL
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ins_prod_insurer ON master_insurance_products(insurer_name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ins_prod_category ON master_insurance_products(category)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ins_prod_status ON master_insurance_products(status)")

    register_schema_documentation(conn, "master_insurance_products", SCHEMA_INSURANCE_PRODUCTS)


def _build_searchable_name(insurer: str, product: str) -> str:
    """Builds a canonical searchable name: 'InsurerBrand - ProductName'."""
    brand = clean_english_text(insurer or "")
    for suffix in (
        " Insurance Company Limited", " Insurance Co. Ltd.", " Life Insurance Limited",
        " Life Insurance Company Limited", " Company Limited", " Insurance Limited",
        " Corporation of India", " Co Ltd", " Limited", " Ltd"
    ):
        if suffix in brand:
            brand = brand.replace(suffix, "")
            break
    brand = brand.strip()
    if insurer and "Life Insurance Corporation" in insurer:
        brand = "LIC"
    prod = clean_english_text(product or "")
    if not brand:
        return prod
    if prod.lower().startswith(brand.lower()):
        return prod
    return f"{brand} - {prod}"


def sync_insurance_products(conn: sqlite3.Connection) -> int:
    """
    Scrapes IRDAI insurance products and writes to SQLite database.
    Returns count of products synced.
    """
    init_insurance_schema(conn)
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")

    scraper = IRDAIProductsScraper()
    batch = []
    count = 0

    for item in scraper.scrape_all_products():
        uin = item.get("uin", "").strip()
        if not uin:
            continue

        product_name = clean_english_text(item.get("product_name", ""))
        insurer_name = clean_english_text(item.get("insurer_name", ""))
        name = _build_searchable_name(insurer_name, product_name)
        category = item.get("category", "Other")
        status = item.get("status", "ACTIVE")
        launch_date = item.get("launch_date")

        batch.append((
            uin, product_name, name, insurer_name, category, status, launch_date, now_iso
        ))

        if len(batch) >= 100:
            _upsert_batch(conn, batch)
            count += len(batch)
            batch.clear()

    if batch:
        _upsert_batch(conn, batch)
        count += len(batch)

    logger.info("Synced %d IRDAI insurance products to master_insurance_products in SQLite.", count)
    return count


def _upsert_batch(conn: sqlite3.Connection, batch: list):
    """Upsert a batch of insurance products. Each item may be a tuple or a dict."""
    if not batch:
        return
    # Normalize dicts to tuples in the expected column order
    normalized = []
    for item in batch:
        if isinstance(item, dict):
            normalized.append((
                item["uin"], item["product_name"], item["name"],
                item["insurer_name"], item["category"], item["status"],
                item.get("launch_date"), item.get("updated_at", ""),
            ))
        else:
            normalized.append(item)
    with transaction(conn) as cursor:
        cursor.executemany("""
            INSERT INTO master_insurance_products (
                uin, product_name, name, insurer_name, category, status, launch_date, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(uin) DO UPDATE SET
                product_name = excluded.product_name,
                name = excluded.name,
                insurer_name = excluded.insurer_name,
                category = excluded.category,
                status = excluded.status,
                launch_date = coalesce(excluded.launch_date, master_insurance_products.launch_date),
                updated_at = excluded.updated_at
        """, normalized)
