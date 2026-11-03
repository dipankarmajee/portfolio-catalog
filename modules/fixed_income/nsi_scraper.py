"""
modules/fixed_income/nsi_scraper.py
Dynamically scrapes official Government of India Small Savings interest rates
and statutory scheme rules from the National Savings Institute (Ministry of Finance).
URL: https://www.nsiindia.gov.in/InternalPage.aspx?Id_Pk=132
"""

from datetime import datetime, timezone
import logging
import re
from typing import Dict, List, Optional
import urllib3

from bs4 import BeautifulSoup

from core.constants import NSI_SCHEME_PATTERNS as SCHEME_PATTERNS
from core.enums import (
    Country,
    Currency,
    FixedIncomeCategory,
    InstrumentStatus,
)
from core.http_client import create_resilient_session
from core.text_utils import clean_english_text, generate_canonical_uid
from core.urls import NSI_SCHEMES_OVERVIEW_URL, NSI_SCHEMES_RATES_URL

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger(__name__)


class NSIScraper:
    def __init__(self):
        self.session = create_resilient_session()

    def scrape_schemes_rates(self) -> List[Dict]:
        """
        Parses official Government of India Small Savings interest rates dynamically from NSI.
        """
        results: List[Dict] = []
        logger.info("Connecting to official NSI interest rates registry at %s...", NSI_SCHEMES_RATES_URL)

        try:
            resp = self.session.get(NSI_SCHEMES_RATES_URL, verify=False, timeout=20)
            if resp.status_code != 200:
                logger.warning("NSI portal returned status %d", resp.status_code)
                return results

            soup = BeautifulSoup(resp.text, "html.parser")
            now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
            today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            # Extract scheme rows
            for tr in soup.find_all("tr"):
                cells = [clean_english_text(td.get_text()) for td in tr.find_all(["td", "th"])]
                if len(cells) < 2:
                    continue

                row_label = cells[0].lower()
                for (code, pattern, name, min_t, max_t, min_dep, max_dep, comp, payout, tax_t, tax_s) in SCHEME_PATTERNS:
                    if re.search(pattern, row_label, re.I):
                        # Extract the most recent valid numeric rate from trailing columns
                        rate_val: Optional[float] = None
                        for val in reversed(cells[1:]):
                            m = re.search(r"(\d+\.\d+)", val)
                            if m:
                                rate_val = float(m.group(1))
                                break

                        if rate_val and rate_val > 0:
                            uid = generate_canonical_uid("FI", code)
                            results.append({
                                "uid": uid,
                                "scheme_code": code,
                                "scheme_name": name,
                                "issuer": "Ministry of Finance (Government of India)",
                                "category": FixedIncomeCategory.SMALL_SAVINGS.value,
                                "country": Country.INDIA.value,
                                "currency": Currency.INR.value,
                                "interest_rate_percent": rate_val,
                                "senior_citizen_rate_percent": rate_val,
                                "compounding_frequency": comp,
                                "payout_frequency": payout,
                                "min_tenure_months": min_t,
                                "max_tenure_months": max_t,
                                "min_deposit": min_dep,
                                "max_deposit": max_dep,
                                "tax_treatment": tax_t,
                                "tax_section": tax_s,
                                "effective_from": today_iso,
                                "formula_notes": f"Statutory rate sourced dynamically from NSI Ministry of Finance.",
                                "status": InstrumentStatus.ACTIVE.value,
                                "updated_at": now_iso,
                            })
                            break
        except Exception as e:
            logger.warning("Dynamic NSI interest rate scraping note: %s", e)

        # De-duplicate by scheme_code keeping earliest match
        seen = set()
        deduped = []
        for r in results:
            if r["scheme_code"] not in seen:
                seen.add(r["scheme_code"])
                deduped.append(r)

        logger.info("Dynamically parsed %d statutory small savings schemes from NSI.", len(deduped))
        return deduped

