"""
Module: scrapers.irdai_scraper
Purpose: Live dynamic scraper for registered Life Insurers.
Target: Life Insurance Council official member directory table.
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

TARGET_URL = "https://www.lifeinscouncil.org/industry_info/members_details.aspx"
REQUEST_TIMEOUT = 30

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

def sanitize_name(raw_name: str) -> str:
    cleaned = re.sub(r"\s+", " ", raw_name).strip()
    # Strip address/telephone blocks if they share the cell
    for sep in ["\n", "\r", "Address:", "Tel:", "Phone:", "Email:", "Fax:", "CIN:"]:
        if sep in cleaned:
            cleaned = cleaned.split(sep)[0].strip()
    return cleaned

def scrape_registered_life_insurers() -> List[Dict[str, str]]:
    logger.info("Connecting to statutory member directory: %s", TARGET_URL)
    session = requests.Session()
    session.mount("https://", SSLHonorAdapter())
    session.headers.update(HEADERS)

    resp = session.get(TARGET_URL, timeout=REQUEST_TIMEOUT)
    logger.info("HTTP Status: %d | Length: %d bytes", resp.status_code, len(resp.content))
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    insurers: Dict[str, Dict[str, str]] = {}

    # Inspect all table rows
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if len(cells) < 2:
            continue

        cell_texts = [c.get_text(strip=True) for c in cells]

        # Look for valid registration sequence (100 to 600)
        reg_num = None
        for idx, val in enumerate(cell_texts):
            clean_digits = re.sub(r"\D", "", val)
            if clean_digits and clean_digits.isdigit() and 100 <= int(clean_digits) <= 600:
                reg_num = clean_digits
                # Company name is in one of the other columns
                name_candidates = [
                    sanitize_name(c) for i, c in enumerate(cell_texts)
                    if i != idx and len(c) > 6 and not re.match(r"^[\d\s\-\/\.]+$", c)
                ]
                if name_candidates:
                    company_name = name_candidates[0]
                    # Filter out header words
                    if not any(header in company_name.lower() for header in ["name of", "regn", "registration"]):
                        insurers[reg_num] = {
                            "insurer_id": f"INS_{reg_num}",
                            "insurer_name": company_name,
                            "reg_number": reg_num,
                            "status": "ACTIVE"
                        }
                break

    # If table scan came up short, parse entity links
    if len(insurers) < 15:
        logger.info("Direct cell scan found %d. Checking anchor elements...", len(insurers))
        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = sanitize_name(a.get_text(strip=True))
            match = re.search(r"[?&]id=(\d{3})", href, re.IGNORECASE)
            if match and len(text) > 6:
                r_num = match.group(1)
                if 100 <= int(r_num) <= 600 and r_num not in insurers:
                    insurers[r_num] = {
                        "insurer_id": f"INS_{r_num}",
                        "insurer_name": text,
                        "reg_number": r_num,
                        "status": "ACTIVE"
                    }

    logger.info("Total dynamic insurers extracted: %d", len(insurers))
    if not insurers:
        raise RuntimeError("Connected to directory, but 0 valid life insurance companies were parsed.")

    return list(insurers.values())