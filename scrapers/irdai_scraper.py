"""
Module: scrapers.irdai_scraper
Purpose: Dedicated scraper for IRDAI statutory life insurers directory.
"""

import logging
from typing import List, Dict
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

IRDAI_URL = "https://irdai.gov.in/list-of-life-insurers"
REQUEST_TIMEOUT_SECONDS = 30

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive"
}


def scrape_registered_life_insurers() -> List[Dict[str, str]]:
    """
    Scrapes the live registered life insurers directory table from IRDAI.

    Returns:
        List of dicts: [{'insurer_id': 'INS_101', 'insurer_name': '...', 'reg_number': '101', 'status': 'ACTIVE'}, ...]
    
    Raises:
        requests.RequestException: If network, status code, or timeout fails.
        ValueError: If the page structure changes or no valid records are found.
    """
    logger.info("Executing dynamic scrape from IRDAI: %s", IRDAI_URL)
    session = requests.Session()
    session.headers.update(HEADERS)

    response = session.get(IRDAI_URL, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    table = soup.find("table")
    if not table:
        raise ValueError(f"No table element detected on {IRDAI_URL}. Layout may have updated.")

    insurers: List[Dict[str, str]] = []
    rows = table.find_all("tr")

    for row in rows:
        cols = row.find_all(["td", "th"])
        col_texts = [c.get_text(strip=True) for c in cols]

        # Expected layout: [Sl. No., Regn. No., Name of Insurer, Date of Registration, ...]
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
        raise ValueError("IRDAI table parsed, but 0 valid numeric registration rows were extracted.")

    logger.info("Scraper successfully extracted %d registered life insurers.", len(insurers))
    return insurers