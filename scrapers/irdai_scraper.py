"""
Module: scrapers.irdai_scraper
Purpose: Robust live scraper for IRDAI life insurers directory.
Handles Drupal table layouts, nested anchors, and formatted registration numbers.
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

IRDAI_LIVE_URL = "https://irdai.gov.in/life-insurers"

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

def clean_company_name(name_raw: str) -> str:
    cleaned = re.sub(r"\s+", " ", name_raw).strip()
    # Strip common trailing contact info if present
    for separator in ["Tel:", "Phone:", "Email:", "Address:", "Fax:"]:
        if separator in cleaned:
            cleaned = cleaned.split(separator)[0].strip()
    return cleaned

def scrape_registered_life_insurers() -> List[Dict[str, str]]:
    logger.info("Connecting to official IRDAI directory: %s", IRDAI_LIVE_URL)
    session = requests.Session()
    session.mount("https://", SSLHonorAdapter())
    session.headers.update(HEADERS)

    resp = session.get(IRDAI_LIVE_URL, timeout=30)
    logger.info("HTTP Status: %d | Response Length: %d bytes", resp.status_code, len(resp.content))
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    insurers: Dict[str, Dict[str, str]] = {}

    # Extraction Strategy 1: Standard Table / Grid Inspection
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if len(cells) < 2:
            continue

        cell_texts = [re.sub(r"\s+", " ", c.get_text(strip=True)) for c in cells]

        # Search for registration number (either clean digits or 'Reg No: 101')
        detected_reg = None
        detected_name = None

        for text in cell_texts:
            # Match 3-digit registration number (IRDAI life insurers range from 101 to 512+)
            reg_match = re.search(r"\b(1\d\d|[2-5]\d\d)\b", text)
            if reg_match:
                detected_reg = reg_match.group(1)
                break

        if detected_reg:
            # Candidate names are columns longer than 6 chars that are not pure dates or pure numbers
            name_candidates = [
                c for c in cell_texts 
                if len(c) > 6 and not re.match(r"^[\d\s\-\/\.]+$", c) and "Date" not in c
            ]
            if name_candidates:
                detected_name = clean_company_name(name_candidates[0])

        if detected_reg and detected_name:
            insurers[detected_reg] = {
                "insurer_id": f"INS_{detected_reg}",
                "insurer_name": detected_name,
                "reg_number": detected_reg,
                "status": "ACTIVE"
            }

    # Extraction Strategy 2: Drupal Views Row Wrapper fallback
    if len(insurers) < 10:
        logger.info("Table extraction returned %d entities; scanning Drupal views rows...", len(insurers))
        for row_div in soup.find_all(["div", "li"], class_=re.compile(r"(views-row|item-list|insurer)")):
            text_block = row_div.get_text(separator=" ", strip=True)
            reg_match = re.search(r"(?:Reg(?:istration)?\.?\s*(?:No\.?)?[:\s]*)?\b(1\d\d|[2-5]\d\d)\b", text_block, re.IGNORECASE)
            
            # Find company title anchor inside row
            anchor = row_div.find("a")
            anchor_text = anchor.get_text(strip=True) if anchor else None

            if reg_match and anchor_text and len(anchor_text) > 6:
                reg_num = reg_match.group(1)
                insurers[reg_num] = {
                    "insurer_id": f"INS_{reg_num}",
                    "insurer_name": clean_company_name(anchor_text),
                    "reg_number": reg_num,
                    "status": "ACTIVE"
                }

    logger.info("Total unique insurers extracted from IRDAI: %d", len(insurers))
    if not insurers:
        snippet = re.sub(r"\s+", " ", soup.get_text()[:400])
        logger.error("Failed to parse IRDAI response. Text preview: %s", snippet)
        raise RuntimeError("IRDAI returned 200, but regex patterns extracted 0 insurer rows.")

    return list(insurers.values())