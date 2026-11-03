"""
modules/fixed_income/us_treasury_scraper.py
Dynamically fetches official daily US Treasury yield curves from the US Department of the Treasury XML feed.
URL: https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml?data=daily_treasury_yield_curve
"""

from datetime import datetime, timezone
import logging
from typing import Dict, List
import xml.etree.ElementTree as ET

from core.constants import TREASURY_SERIES
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
from core.urls import US_TREASURY_YIELD_CURVE_URL

logger = logging.getLogger(__name__)


class USTreasuryScraper:
    def __init__(self):
        self.session = create_resilient_session()

    def fetch_latest_yields(self) -> List[Dict]:
        """
        Fetches the latest yield curve entries from US Treasury XML.
        """
        results: List[Dict] = []
        current_year = datetime.now().year
        url = US_TREASURY_YIELD_CURVE_URL.format(year=current_year)
        logger.info("Connecting to official US Treasury yield curve at %s...", url)

        try:
            resp = self.session.get(url, timeout=20)
            if resp.status_code != 200:
                logger.warning("US Treasury yield curve returned status %d", resp.status_code)
                return results

            root = ET.fromstring(resp.content)
            entries = root.findall("{http://www.w3.org/2005/Atom}entry")
            if not entries:
                return results

            # Most recent daily entry is the last entry in Atom feed
            last_entry = entries[-1]
            content = last_entry.find("{http://www.w3.org/2005/Atom}content")
            if content is None:
                return results

            props = content.find("{http://schemas.microsoft.com/ado/2007/08/dataservices/metadata}properties")
            if props is None:
                return results

            yield_data = {}
            for child in props:
                tag = child.tag.split("}")[-1]
                if child.text:
                    yield_data[tag] = child.text.strip()

            date_val = yield_data.get("NEW_DATE", "")[:10]
            now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")

            for code, name, field, min_t, max_t in TREASURY_SERIES:
                rate_str = yield_data.get(field)
                if not rate_str:
                    continue
                try:
                    rate = float(rate_str)
                except ValueError:
                    continue

                uid = generate_canonical_uid("FI", code)
                results.append({
                    "uid": uid,
                    "scheme_code": code,
                    "scheme_name": name,
                    "issuer": "US Department of the Treasury",
                    "category": FixedIncomeCategory.TREASURY_BILL.value if min_t <= 12 else FixedIncomeCategory.GOVERNMENT_SECURITY.value,
                    "country": Country.UNITED_STATES.value,
                    "currency": Currency.USD.value,
                    "interest_rate_percent": rate,
                    "senior_citizen_rate_percent": rate,
                    "compounding_frequency": CompoundingFrequency.SEMI_ANNUAL.value,
                    "payout_frequency": PayoutFrequency.SEMI_ANNUAL.value if min_t > 12 else PayoutFrequency.AT_MATURITY.value,
                    "min_tenure_months": min_t,
                    "max_tenure_months": max_t,
                    "min_deposit": 100.0,
                    "max_deposit": 0.0,
                    "tax_treatment": TaxTreatment.TAXABLE.value,
                    "tax_section": "US Federal Taxable / State Exempt",
                    "effective_from": date_val or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    "formula_notes": "Sourced dynamically from US Department of the Treasury daily yield curve feed.",
                    "status": InstrumentStatus.ACTIVE.value,
                    "updated_at": now_iso,
                })
        except Exception as e:
            logger.warning("Dynamic US Treasury yield parsing note: %s", e)

        logger.info("Dynamically parsed %d US Treasury benchmark yields.", len(results))
        return results

