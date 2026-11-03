"""
modules/fixed_income/fixed_income_collector.py
Synchronizes statutory Fixed Income instruments dynamically from official government
and regulatory portals: National Savings Institute (Ministry of Finance),
US Department of the Treasury, and Reserve Bank of India.
Strictly dynamic: zero hardcoded interest rates or static fallback values.
"""

from datetime import datetime, timezone
import logging
from typing import List

from core.database import register_schema_documentation, transaction
from core.schemas import SCHEMA_FIXED_INCOME
from modules.fixed_income.nsi_scraper import NSIScraper
from modules.fixed_income.rbi_scraper import RBIScraper
from modules.fixed_income.us_treasury_scraper import USTreasuryScraper

logger = logging.getLogger(__name__)


def init_fixed_income_schema(conn):
    with transaction(conn) as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS master_fixed_income (
                uid TEXT PRIMARY KEY,
                scheme_code TEXT NOT NULL UNIQUE,
                scheme_name TEXT NOT NULL,
                issuer TEXT NOT NULL,
                category TEXT NOT NULL,
                country TEXT NOT NULL,
                currency TEXT NOT NULL,
                interest_rate_percent REAL NOT NULL,
                senior_citizen_rate_percent REAL NOT NULL DEFAULT 0.0,
                compounding_frequency TEXT NOT NULL,
                payout_frequency TEXT NOT NULL,
                min_tenure_months INTEGER NOT NULL,
                max_tenure_months INTEGER NOT NULL DEFAULT 0,
                min_deposit REAL NOT NULL DEFAULT 0.0,
                max_deposit REAL NOT NULL DEFAULT 0.0,
                tax_treatment TEXT NOT NULL,
                tax_section TEXT,
                effective_from TEXT,
                formula_notes TEXT,
                status TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_fi_code ON master_fixed_income(scheme_code)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_fi_cat ON master_fixed_income(category)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_fi_country ON master_fixed_income(country)")
    register_schema_documentation(conn, "master_fixed_income", SCHEMA_FIXED_INCOME)


def sync_fixed_income(conn) -> int:
    init_fixed_income_schema(conn)

    # 1. Fetch dynamic Government of India Small Savings from NSI
    nsi = NSIScraper()
    schemes = nsi.scrape_schemes_rates()

    # 2. Fetch dynamic US Treasury yield curves
    treasuries = USTreasuryScraper()
    schemes.extend(treasuries.fetch_latest_yields())

    # 3. Fetch dynamic RBI policy benchmark rates
    rbi = RBIScraper()
    schemes.extend(rbi.fetch_policy_rates())

    if not schemes:
        logger.warning("No fixed income schemes retrieved from live endpoints.")
        return 0

    with transaction(conn) as cursor:
        cursor.executemany("""
            INSERT INTO master_fixed_income (
                uid, scheme_code, scheme_name, issuer, category, country, currency,
                interest_rate_percent, senior_citizen_rate_percent,
                compounding_frequency, payout_frequency, min_tenure_months,
                max_tenure_months, min_deposit, max_deposit, tax_treatment,
                tax_section, effective_from, formula_notes, status, updated_at
            ) VALUES (
                :uid, :scheme_code, :scheme_name, :issuer, :category, :country, :currency,
                :interest_rate_percent, :senior_citizen_rate_percent,
                :compounding_frequency, :payout_frequency, :min_tenure_months,
                :max_tenure_months, :min_deposit, :max_deposit, :tax_treatment,
                :tax_section, :effective_from, :formula_notes, :status, :updated_at
            )
            ON CONFLICT(scheme_code) DO UPDATE SET
                scheme_name = excluded.scheme_name,
                issuer = excluded.issuer,
                category = excluded.category,
                interest_rate_percent = excluded.interest_rate_percent,
                senior_citizen_rate_percent = excluded.senior_citizen_rate_percent,
                compounding_frequency = excluded.compounding_frequency,
                payout_frequency = excluded.payout_frequency,
                min_tenure_months = excluded.min_tenure_months,
                max_tenure_months = excluded.max_tenure_months,
                min_deposit = excluded.min_deposit,
                max_deposit = excluded.max_deposit,
                tax_treatment = excluded.tax_treatment,
                tax_section = excluded.tax_section,
                effective_from = excluded.effective_from,
                formula_notes = excluded.formula_notes,
                status = excluded.status,
                updated_at = excluded.updated_at
        """, schemes)

    logger.info("Successfully synced %d dynamic fixed income instruments.", len(schemes))
    return len(schemes)
