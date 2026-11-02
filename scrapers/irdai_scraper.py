"""
Module: scrapers.irdai_scraper
Purpose: Resilient live scraper for statutory Life Insurers directory.
Targets active Life Insurance Council & IRDAI endpoints.
"""

import logging
import sys
import re
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

# Multi-endpoint discovery list covering verified public regulatory paths
TARGET_ENDPOINTS = [
    "https://www.lifeinscouncil.org/industry_info/members_details.aspx",
    "https://www.lifeinscouncil.org/industry_info/member_details.aspx",
    "https://www.lifeinscouncil.org/industry_info/",
    "https://irdai.gov.in/life-insurers"
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive"
}

class SSLHonorAdapter(HTTPAdapter):
    """Bypasses legacy TLS/cipher negotiation strictness on cloud runners."""
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.load_default_certs()
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)

def scrape_registered_life_insurers() -> List[Dict[str, str]]:
    session = requests.Session()
    session.mount("https://", SSLHonorAdapter())
    session.headers.update(HEADERS)

    for url in TARGET_ENDPOINTS:
        logger.info("Attempting scrape from statutory endpoint: %s", url)
        try:
            resp = session.get(url, timeout=25)
            logger.info("HTTP Status: %d | Length: %d bytes", resp.status_code, len(resp.content))
            if resp.status_code != 200 or len(resp.content) < 1000:
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            insurers: Dict[str, Dict[str, str]] = {}

            # Strategy A: Extract from standard HTML table grids
            for tr in soup.find_all("tr"):
                cols = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
                if len(cols) >= 2:
                    for idx, val in enumerate(cols):
                        # Detect statutory IRDAI Registration Numbers (typically 101 to 600)
                        if val.isdigit() and 100 <= int(val) <= 600:
                            reg_num = val
                            # Locate the corresponding corporation name in the remaining columns
                            name_candidates = [c for i, c in enumerate(cols) if i != idx and len(c) > 6 and not c.isdigit()]
                            if name_candidates:
                                raw_name = name_candidates[0]
                                clean_name = " ".join(raw_name.split())
                                insurers[reg_num] = {
                                    "insurer_id": f"INS_{reg_num}",
                                    "insurer_name": clean_name,
                                    "reg_number": reg_num,
                                    "status": "ACTIVE"
                                }
                            break

            # Strategy B: If table parsing yielded few results, extract from detail links/anchors
            if len(insurers) < 15:
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    text = a.get_text(strip=True)
                    # Often links are structured like: members_details.aspx?id=101 or contains company names
                    match = re.search(r"[?&]id=(\d{3})", href, re.IGNORECASE)
                    if match and len(text) > 4:
                        reg_num = match.group(1)
                        if 100 <= int(reg_num) <= 600:
                            insurers[reg_num] = {
                                "insurer_id": f"INS_{reg_num}",
                                "insurer_name": text,
                                "reg_number": reg_num,
                                "status": "ACTIVE"
                            }

            if len(insurers) >= 15:
                logger.info("Successfully extracted %d insurers from %s", len(insurers), url)
                return list(insurers.values())
            else:
                logger.warning("Endpoint %s yielded only %d valid records; trying next source.", url, len(insurers))

        except Exception as exc:
            logger.warning("Error querying %s: %s", url, exc)

    raise RuntimeError("All statutory insurer endpoints failed or returned 0 rows.")