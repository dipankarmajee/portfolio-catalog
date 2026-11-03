"""
core/config.py
Central configuration and directory path definitions.
"""

from pathlib import Path

# Base Paths
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DOCS_DIR = BASE_DIR / "documentation"
FALLBACK_DIR = BASE_DIR / "fallback"

# Ensure directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
DOCS_DIR.mkdir(parents=True, exist_ok=True)
FALLBACK_DIR.mkdir(parents=True, exist_ok=True)

# Database File Paths
DB_EQUITIES_ETFS = DATA_DIR / "master_equities_etfs.sqlite"
DB_MUTUAL_FUNDS = DATA_DIR / "master_mutual_funds.sqlite"
DB_FIXED_INCOME = DATA_DIR / "master_fixed_income.sqlite"
DB_NPS = DATA_DIR / "master_nps.sqlite"
DB_COMMODITIES_CRYPTO = DATA_DIR / "master_commodities_crypto.sqlite"
DB_INSURERS_ULIPS = DATA_DIR / "master_insurers_ulips.sqlite"

# Schema Documentation Output
OUTPUT_DOCS_PATH = DOCS_DIR / "DATABASE_SCHEMA.md"

# Network & HTTP Defaults
DEFAULT_TIMEOUT = 30
MAX_RETRIES = 3
BACKOFF_FACTOR = 1.0

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}

# SEC EDGAR requires a specific User-Agent format: Sample Company Name AdminContact@<sample company domain>.com
SEC_HEADERS = {
    "User-Agent": "PortfolioCatalogMaster/2.0 (contact@portfoliocatalog.local)",
    "Accept-Encoding": "gzip, deflate",
    "Host": "www.sec.gov",
}

