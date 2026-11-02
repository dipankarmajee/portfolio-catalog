"""
Module: scrapers.irdai_scraper
Purpose: Live scraping logic for IRDAI Life Insurers Directory.
"""

import logging
from typing import List, Dict
import requests
from bs4 import BeautifulSoup
from urllib3.util import create_urllib3_context
from requests.adapters import HTTPAdapter

logger = logging.getLogger(__name__)

IRDAI_URL = "https://irdai.gov.in/list-of-life-insurers"
REQUEST_TIMEOUT_SECONDS = 30

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive"
}


class SSLHonorAdapter(HTTPAdapter):
    """Ensures compatibility with government portal TLS handshakes on cloud runners."""
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.load_default_certs()
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


def scrape_registered_life_insurers() -> List[Dict[str, str]]:
    """
    Scrapes active life insurers directly from IRDAI's directory.
    
    Returns:
        List of dictionaries with insurer_id, insurer_name, reg_number, status.
        
    Raises:
        requests.RequestException: On connection/HTTP errors.
        RuntimeError: If the table structure is missing or contains no valid rows.
    """
    logger.info("Connecting to IRDAI live directory: %s", IRDAI_URL)
    session = requests.Session()
    session.mount("https://", SSLHonorAdapter())
    session.headers.update(HEADERS)

    response = session.get(IRDAI_URL, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    table = soup.find("table")
    if not table:
        raise RuntimeError(f"No table element discovered on {IRDAI_URL}")

    insurers: List[Dict[str, str]] = []
    for row in table.find_all("tr"):
        cols = row.find_all(["td", "th"])
        col_texts = [c.get_text(strip=True) for c in cols]

        # Expected layout: [Sl No, Regn No, Insurer Name, Registration Date, ...]
        if len(col_texts) >= 3 and col_texts[1].isdigit():
            reg_num = col_texts[1].strip()
            raw_name = col_texts[2].strip()
            clean_name = " ".join(raw_name.split())

            insurers.append({
                "insurer_id": f"INS_{reg_num}",
                "insurer_name": clean_name,
                "reg_number": reg_num,
                "status": "ACTIVE"
            })

    if not insurers:
        raise RuntimeError("IRDAI table located, but zero valid insurer rows were extracted.")

    logger.info("Successfully fetched %d registered insurers from IRDAI.", len(insurers))
    return insurers