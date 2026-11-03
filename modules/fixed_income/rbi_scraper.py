"""
modules/fixed_income/rbi_scraper.py
Dynamically scrapes official Reserve Bank of India (RBI) policy rates and statutory benchmarks.
URL: https://www.rbi.org.in/
"""

from datetime import datetime, timezone
import logging
import re
from typing import Dict, List

from bs4 import BeautifulSoup

from core.enums import (
    CompoundingFrequency,
    Country,
    Currency,
    FixedIncomeCategory,
    InstrumentStatus,
    PayoutFrequency,
    TaxTreatment,
)
from core.http_client import create_resilient_session
from core.text_utils import generate_canonical_uid
from core.urls import RBI_HOME_URL

logger = logging.getLogger(__name__)

RBI_RATE_TARGETS = [
    ("RBI_REPO_RATE", r"policy\s+repo\s+rate", "RBI Policy Repo Rate", FixedIncomeCategory.POLICY_RATE.value),
    ("RBI_BANK_RATE", r"bank\s+rate", "RBI Bank Rate Benchmark", FixedIncomeCategory.POLICY_RATE.value),
    ("RBI_REVERSE_REPO", r"reverse\s+repo\s+rate", "RBI Fixed Reverse Repo Rate", FixedIncomeCategory.POLICY_RATE.value),
]


class RBIScraper:
    def __init__(self):
        self.session = create_resilient_session()

    def fetch_policy_rates(self) -> List[Dict]:
        """
        Scrapes official monetary policy rates dynamically from the RBI portal.
        """
        results: List[Dict] = []
        logger.info("Connecting to official RBI portal at %s...", RBI_HOME_URL)

        try:
            resp = self.session.get(RBI_HOME_URL, timeout=15)
            if resp.status_code != 200:
                logger.warning("RBI portal returned status %d", resp.status_code)
                return results

            soup = BeautifulSoup(resp.text, "html.parser")
            now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
            today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            for tr in soup.find_all("tr"):
                text = tr.get_text().strip().replace("\n", " ")
                for code, pattern, name, cat in RBI_RATE_TARGETS:
                    if re.search(pattern, text, re.I):
                        m = re.search(r"(\d+\.\d+)\s*%", text)
                        if m:
                            rate = float(m.group(1))
                            uid = generate_canonical_uid("FI", code)
                            results.append({
                                "uid": uid,
                                "scheme_code": code,
                                "scheme_name": name,
                                "issuer": "Reserve Bank of India (RBI)",
                                "category": cat,
                                "country": Country.INDIA.value,
                                "currency": Currency.INR.value,
                                "interest_rate_percent": rate,
                                "senior_citizen_rate_percent": rate,
                                "compounding_frequency": CompoundingFrequency.SIMPLE.value,
                                "payout_frequency": PayoutFrequency.NOT_APPLICABLE.value,
                                "min_tenure_months": 0,
                                "max_tenure_months": 0,
                                "min_deposit": 0.0,
                                "max_deposit": 0.0,
                                "tax_treatment": TaxTreatment.TAXABLE.value,
                                "tax_section": "Monetary Benchmark",
                                "effective_from": today_iso,
                                "formula_notes": "Official sovereign monetary policy rate published dynamically by RBI.",
                                "status": InstrumentStatus.ACTIVE.value,
                                "updated_at": now_iso,
                            })
                            break
        except Exception as e:
            logger.warning("Dynamic RBI policy rate scraping note: %s", e)

        # De-duplicate by scheme_code
        seen = set()
        deduped = []
        for r in results:
            if r["scheme_code"] not in seen:
                seen.add(r["scheme_code"])
                deduped.append(r)

        logger.info("Dynamically parsed %d policy benchmark rates from RBI.", len(deduped))
        return deduped

