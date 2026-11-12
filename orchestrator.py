"""
orchestrator.py
Unified Command-Line Interface and Pipeline Orchestrator for portfolio-catalog.
"""

import argparse
import logging
import sys
import time

from core.config import (
    DB_COMMODITIES,
    DB_CRYPTO,
    DB_EQUITIES_ETFS,
    DB_FIXED_INCOME,
    DB_INSURERS_ULIPS,
    DB_MUTUAL_FUNDS,
    DB_NPS,
)
from core.database import get_connection
import generate_schema_docs
from modules.commodities.ibja_collector import sync_commodities
from modules.crypto.crypto_collector import sync_crypto
from modules.equities.nse_collector import sync_nse_equities
from modules.equities.sec_edgar_collector import sync_sec_edgar_equities
from modules.fixed_income.fixed_income_collector import sync_fixed_income
from modules.mutual_funds.amfi_collector import sync_amfi_mutual_funds
from modules.nps.nps_collector import sync_nps
from modules.ulips.ulip_collector import sync_insurers_ulips
from modules.insurance.insurance_collector import sync_insurance_products

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("orchestrator")


def run_equities():
    logger.info("=== Starting Equities & ETFs Sync ===")
    conn = get_connection(DB_EQUITIES_ETFS)
    try:
        nse_count = sync_nse_equities(conn)
        sec_count = sync_sec_edgar_equities(conn)
        logger.info("Equities Complete: %d NSE + %d US SEC instruments.", nse_count, sec_count)
    finally:
        conn.close()


def run_mutual_funds():
    logger.info("=== Starting Mutual Funds Sync ===")
    conn = get_connection(DB_MUTUAL_FUNDS)
    try:
        mf_count = sync_amfi_mutual_funds(conn)
        logger.info("Mutual Funds Complete: %d AMFI schemes.", mf_count)
    finally:
        conn.close()


def run_fixed_income():
    logger.info("=== Starting Fixed Income Sync ===")
    conn = get_connection(DB_FIXED_INCOME)
    try:
        fi_count = sync_fixed_income(conn)
        logger.info("Fixed Income Complete: %d statutory schemes.", fi_count)
    finally:
        conn.close()


def run_nps():
    logger.info("=== Starting National Pension System (NPS) Sync ===")
    conn = get_connection(DB_NPS)
    try:
        nps_count = sync_nps(conn)
        logger.info("NPS Complete: %d PFM schemes.", nps_count)
    finally:
        conn.close()


def run_commodities():
    logger.info("=== Starting Commodities Sync ===")
    conn = get_connection(DB_COMMODITIES)
    try:
        comm_count = sync_commodities(conn)
        logger.info("Commodities Complete: %d benchmarks.", comm_count)
    finally:
        conn.close()


def run_crypto():
    logger.info("=== Starting Crypto Sync ===")
    conn = get_connection(DB_CRYPTO)
    try:
        crypto_count = sync_crypto(conn)
        logger.info("Crypto Complete: %d assets.", crypto_count)
    finally:
        conn.close()


def run_ulips():
    logger.info("=== Starting Insurers & ULIPs Sync ===")
    conn = get_connection(DB_INSURERS_ULIPS)
    try:
        ulip_count = sync_insurers_ulips(conn)
        logger.info("Insurers & ULIPs Complete: %d funds synced.", ulip_count)
    finally:
        conn.close()


def run_insurance_products():
    logger.info("=== Starting IRDAI Life Insurance Products Sync ===")
    conn = get_connection(DB_INSURERS_ULIPS)
    try:
        prod_count = sync_insurance_products(conn)
        logger.info("Insurance Products Complete: %d official IRDAI products synced.", prod_count)
    finally:
        conn.close()


def run_all():
    start_time = time.time()
    logger.info("************************************************************")
    logger.info("Starting Full Master Catalog Synchronization Pipeline")
    logger.info("************************************************************")

    # 1. Equities & ETFs
    try:
        run_equities()
    except Exception as e:
        logger.error("Equities pipeline error: %s", e)

    # 2. Mutual Funds
    try:
        run_mutual_funds()
    except Exception as e:
        logger.error("Mutual Funds pipeline error: %s", e)

    # 3. Fixed Income
    try:
        run_fixed_income()
    except Exception as e:
        logger.error("Fixed Income pipeline error: %s", e)

    # 4. NPS
    try:
        run_nps()
    except Exception as e:
        logger.error("NPS pipeline error: %s", e)

    # 5. Commodities & Crypto
    try:
        run_commodities()
        run_crypto()
    except Exception as e:
        logger.error("Commodities/Crypto pipeline error: %s", e)

    # 6. Insurers & ULIPs
    try:
        run_ulips()
    except Exception as e:
        logger.error("ULIPs pipeline error: %s", e)

    # 7. IRDAI Life Insurance Products
    try:
        run_insurance_products()
    except Exception as e:
        logger.error("Insurance products pipeline error: %s", e)

    # 8. Generate Schema Documentation
    logger.info("=== Regenerating Schema Documentation ===")
    try:
        generate_schema_docs.run()
    except Exception as e:
        logger.error("Schema documentation error: %s", e)

    elapsed = round(time.time() - start_time, 2)
    logger.info("************************************************************")
    logger.info("Master Pipeline Complete in %s seconds.", elapsed)
    logger.info("************************************************************")


def main():
    parser = argparse.ArgumentParser(description="Portfolio Catalog Master Pipeline Orchestrator")
    parser.add_argument("--all", action="store_true", help="Run full pipeline across all asset classes")
    parser.add_argument(
        "--module",
        choices=["equities", "mutual_funds", "fixed_income", "nps", "commodities", "crypto", "ulips", "insurance_products"],
        help="Run a specific asset module"
    )
    parser.add_argument("--docs", action="store_true", help="Regenerate schema documentation only")

    args = parser.parse_args()

    if args.docs:
        generate_schema_docs.run()
        return

    if args.module:
        module_runners = {
            "equities": run_equities,
            "mutual_funds": run_mutual_funds,
            "fixed_income": run_fixed_income,
            "nps": run_nps,
            "commodities": run_commodities,
            "crypto": run_crypto,
            "ulips": run_ulips,
            "insurance_products": run_insurance_products,
        }
        module_runners[args.module]()
        generate_schema_docs.run()
        return

    # Default: run all
    run_all()


if __name__ == "__main__":
    main()

