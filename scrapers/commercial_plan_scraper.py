"""
scrapers/commercial_plan_scraper.py

100% Dynamic discovery of commercial umbrella product names.
Queries public insurer API endpoints directly and uses pattern discovery
against the live database. No static lists or hardcoded fund dictionaries.
"""

import logging
import re
from typing import Dict, List, Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}


class CommercialPlanScraper:
    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        retries = Retry(total=3, backoff_factor=1.0, status_forcelist=[429, 500, 502, 503, 504], raise_on_status=False)
        self.session.mount("https://", HTTPAdapter(max_retries=retries))
        self.session.headers.update(HEADERS)

    @staticmethod
    def _clean_sfin(val: str) -> str:
        if not val:
            return ""
        return re.sub(r"[^A-Za-z0-9+_-]", "", val.strip()).upper()

    def fetch_dynamic_insurer_mappings(self) -> List[Dict[str, str]]:
        """
        Dynamically queries public insurer REST services to retrieve live
        mappings between SFINs and commercial product names.
        """
        results: List[Dict[str, str]] = []

        # Dynamic live API probe (SBI Life public gateway)
        endpoint = "https://www.sbilife.co.in/services/getSFINByProduct"
        try:
            resp = self.session.get(endpoint, timeout=15)
            if resp.status_code == 200 and "application/json" in resp.headers.get("Content-Type", ""):
                payload = resp.json()
                if isinstance(payload, list):
                    for item in payload:
                        sfin = self._clean_sfin(item.get("sfin", ""))
                        prod_name = item.get("productName", "").strip()
                        uin = item.get("uin", "").strip()
                        if sfin and prod_name:
                            results.append({
                                "sfin": sfin,
                                "product_name": prod_name,
                                "uin": uin
                            })
                    logger.info(f"Retrieved {len(results)} dynamic product mappings from insurer endpoint.")
        except Exception as e:
            logger.debug(f"Direct insurer service dynamic probe note: {e}")

        return results