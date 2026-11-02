"""
Module: scrapers.irdai_scraper
Purpose: Live scraping logic for statutory Life Insurers directory.
"""

import logging
import sys
from typing import List, Dict
import requests
from bs4 import BeautifulSoup
from urllib3.util import create_urllib3_context
from requests.adapters import HTTPAdapter

logger = logging.getLogger("scrapers.irdai")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] [IRDAI_SCRAPER] %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

# Primary statutory repository and official mirror
ENDPOINTS = [
    "https://www.lifeinscouncil.org/industry_info/members.aspx",
    "https://irdai.gov.in/regulated-entities/life-insurers"
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive"
}

class SSLHonorAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.load_default_certs()
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)

def scrape_registered_life_insurers() -> List[Dict[str, str]]:
    session = requests.Session()
    session.mount("https://", SSLHonorAdapter())
    session.headers.update(HEADERS)

    last_error = None
    for url in ENDPOINTS:
        logger.info("Attempting scrape from statutory endpoint: %s", url)
        try:
            resp = session.get(url, timeout=25)
            logger.info("HTTP Status: %d | Length: %d bytes", resp.status_code, len(resp.content))
            if resp.status_code != 200:
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            insurers: List[Dict[str, str]] = []

            # Case A: Table layout (Life Insurance Council or IRDAI table)
            for tr in soup.find_all("tr"):
                cols = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
                if len(cols) >= 2:
                    # Look for numerical registration or sequence
                    for val in cols:
                        if val.isdigit() and 100 <= int(val) <= 600:
                            reg_num = val
                            # Find the company name column
                            name_candidates = [c for c in cols if len(c) > 6 and not c.isdigit()]
                            if name_candidates:
                                clean_name = name_candidates[0].split("\n")[0].strip()
                                insurers.append({
                                    "insurer_id": f"INS_{reg_num}",
                                    "insurer_name": clean_name,
                                    "reg_number": reg_num,
                                    "status": "ACTIVE"
                                })
                            break

            # Deduplicate by reg_number
            unique_insurers = {i["reg_number"]: i for i in insurers}.values()
            result = list(unique_insurers)

            if len(result) >= 15:
                logger.info("Successfully extracted %d insurers from %s", len(result), url)
                return result

        except Exception as e:
            logger.warning("Endpoint %s failed: %s", url, e)
            last_error = e

    raise RuntimeError(f"All statutory insurer endpoints failed or returned 0 rows. Last error: {last_error}")