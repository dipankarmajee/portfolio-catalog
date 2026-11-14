"""
modules/fixed_income/sgb_scraper.py
Automated dynamic scraper for Sovereign Gold Bonds (SGB) from official exchange and regulatory endpoints.
Primary source: Official NSE India API (https://www.nseindia.com/api/sovereign-gold-bonds)
Secondary source: Official NSE Bhavcopy & regulatory archive feeds.

Strictly dynamic: zero hardcoded series or static fallback arrays.
"""

import calendar
from datetime import datetime, timezone
import logging
import re
from typing import Dict, Generator, List, Optional, Tuple

import requests
from core.http_client import create_resilient_session
from core.urls import NSE_HOME_URL, NSE_SGB_API_URL

logger = logging.getLogger(__name__)

# Map of month abbreviations appearing in SGB symbols to month numbers and names
MONTH_CODES: Dict[str, Tuple[int, str]] = {
    "JAN": (1, "January"),
    "FEB": (2, "February"),
    "MAR": (3, "March"),
    "MR": (3, "March"),
    "APR": (4, "April"),
    "MAY": (5, "May"),
    "JUN": (6, "June"),
    "JU": (6, "June"),
    "JUL": (7, "July"),
    "AUG": (8, "August"),
    "SEP": (9, "September"),
    "OCT": (10, "October"),
    "OC": (10, "October"),
    "NOV": (11, "November"),
    "NV": (11, "November"),
    "N": (11, "November"),
    "DEC": (12, "December"),
    "DE": (12, "December"),
    "DC": (12, "December"),
    "D": (12, "December"),
    "J": (1, "January"),
}

# Regex to parse SGB symbol structure:
# SGB + MonthCode (1-3 letters) + Year (2 digits) + Series in Roman numerals (optional)
_SGB_SYMBOL_REGEX = re.compile(r"^SGB([A-Z]{1,3})([0-9]{2})([IVX]*)$", re.IGNORECASE)

# Statutory statutory coupon rate for Sovereign Gold Bonds
STATUTORY_COUPON_RATE = 2.50


def parse_sgb_symbol_metadata(symbol: str) -> Optional[Dict]:
    """
    Dynamically derives series name, issue date, maturity date, and semi-annual coupon schedule
    from the official exchange symbol without hardcoding.
    """
    clean_sym = symbol.strip().upper()
    match = _SGB_SYMBOL_REGEX.match(clean_sym)
    if not match:
        return None

    m_code, yr_str, series_roman = match.groups()
    if m_code not in MONTH_CODES:
        return None

    m_num, m_name = MONTH_CODES[m_code]
    mat_year = 2000 + int(yr_str)
    issue_year = mat_year - 8

    # Semi-annual coupon payout months (every 6 months)
    c1 = m_num
    c2 = (m_num + 5) % 12 + 1
    coupon_months = f"{min(c1, c2)},{max(c1, c2)}"

    # Statutory coupon day defaults to 1st of month (or mid-month)
    coupon_day = 1

    last_day_mat = calendar.monthrange(mat_year, m_num)[1]
    issue_date = f"{issue_year:04d}-{m_num:02d}-01"
    maturity_date = f"{mat_year:04d}-{m_num:02d}-{last_day_mat:02d}"

    # Indian fiscal year: Apr-Mar (e.g. 2023-24)
    if m_num >= 4:
        fiscal_year = f"{issue_year}-{str(issue_year + 1)[-2:]}"
    else:
        fiscal_year = f"{issue_year - 1}-{str(issue_year)[-2:]}"

    series_display = f"Series {series_roman}" if series_roman else "Series I"
    clean_name = f"SGB {fiscal_year} {series_display}".strip()

    return {
        "symbol": clean_sym,
        "name": clean_name,
        "series": series_display,
        "fiscal_year": fiscal_year,
        "issue_date": issue_date,
        "maturity_date": maturity_date,
        "coupon_rate": STATUTORY_COUPON_RATE,
        "coupon_months": coupon_months,
        "coupon_day": coupon_day,
    }


class SGBScraper:
    """
    Automated scraper for Sovereign Gold Bonds from regulatory/exchange endpoints.
    """

    def __init__(self, session: Optional[requests.Session] = None):
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.nseindia.com/market-data/sovereign-gold-bonds",
        }
        self.session = session or create_resilient_session(headers=headers)

    def _init_cookies(self):
        """Warm up session cookies on NSE homepage."""
        try:
            self.session.get(NSE_HOME_URL, timeout=15)
        except Exception as e:
            logger.debug("Failed to warm up NSE session cookies: %s", e)

    def fetch_all_tranches(self) -> Generator[Dict, None, None]:
        """
        Dynamically fetches all active & past SGB tranches from the official NSE API.
        Yields normalized tranche dictionaries.
        """
        logger.info("Connecting to official NSE SGB directory at %s...", NSE_SGB_API_URL)
        self._init_cookies()

        try:
            resp = self.session.get(NSE_SGB_API_URL, timeout=20)
            if resp.status_code != 200:
                logger.warning("NSE SGB API responded with HTTP %d", resp.status_code)
                return

            payload = resp.json()
            items = payload.get("data", [])
            logger.info("Retrieved %d SGB tranches dynamically from NSE.", len(items))

            now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            for item in items:
                sym = (item.get("symbol") or "").strip().upper()
                if not sym:
                    continue

                meta = parse_sgb_symbol_metadata(sym)
                if not meta:
                    logger.debug("Could not parse metadata for SGB symbol: %s", sym)
                    continue

                # Parse issue price
                raw_price = item.get("issue_price")
                try:
                    issue_price = float(raw_price) if raw_price else 0.0
                except (ValueError, TypeError):
                    issue_price = 0.0

                # Parse latest traded market price
                raw_ltp = item.get("ltP")
                try:
                    latest_price = float(raw_ltp) if raw_ltp else None
                except (ValueError, TypeError):
                    latest_price = None

                # Status: ACTIVE vs REDEEMED based on maturity date
                is_matured = meta["maturity_date"] < today_str
                status = "REDEEMED" if is_matured else "ACTIVE"

                uid = f"SGB_{sym}"

                yield {
                    "uid": uid,
                    "symbol": sym,
                    "name": meta["name"],
                    "series": meta["series"],
                    "issue_date": meta["issue_date"],
                    "maturity_date": meta["maturity_date"],
                    "issue_price": issue_price,
                    "coupon_rate": meta["coupon_rate"],
                    "coupon_months": meta["coupon_months"],
                    "coupon_day": meta["coupon_day"],
                    "latest_price": latest_price,
                    "price_date": today_str if latest_price else None,
                    "status": status,
                    "updated_at": now_iso,
                }

        except Exception as exc:
            logger.error("Failed to fetch SGB tranches from NSE API: %s", exc)
            return
