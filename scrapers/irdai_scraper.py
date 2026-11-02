"""
Module: scrapers.irdai_scraper
Purpose: 100% Dynamic, paginated scraper for official IRDAI Life Insurers directory.
Inspects main view content containers to bypass repetitive header/nav links.
"""

import logging
import sys
import re
from typing import List, Dict
from urllib.parse import urljoin
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

BASE_IRDAI_URL = "https://irdai.gov.in/life-insurers"
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

def sanitize_text(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    for delimiter in ["Tel:", "Phone:", "Email:", "Address:", "Fax:", "CIN:", "Website:", "Date of Registration"]:
        if delimiter in cleaned:
            cleaned = cleaned.split(delimiter)[0].strip()
    return cleaned

def is_corporate_insurer(name: str) -> bool:
    if len(name) < 6 or len(name) > 120:
        return False
    lower = name.lower()
    
    # Exclude navigational/header links
    noise = [
        "skip to", "accessibility", "contrast", "text size", "home", "about us",
        "regulations", "guidelines", "circulars", "press release", "public notice",
        "consumer", "ombudsman", "grievance", "contact us", "feedback", "faq",
        "act & rules", "annual reports", "handbook", "overview", "types of"
    ]
    if any(n in lower for n in noise):
        return False

    has_life = "life" in lower or "lic" in lower
    has_ins = any(term in lower for term in ["insurance", "assurance", "corporation", "ltd", "limited", "co."])
    return has_life or has_ins

def extract_reg_number(text: str) -> str:
    match = re.search(r"(?:reg(?:istration)?\.?\s*(?:no\.?)?[:\s]*)?\b(1\d\d|[2-5]\d\d)\b", text, re.IGNORECASE)
    if match:
        return match.group(1)
    return ""

def extract_entities_from_page(soup: BeautifulSoup) -> Dict[str, Dict[str, str]]:
    page_insurers: Dict[str, Dict[str, str]] = {}

    # Target the main body/content region to ignore header/footer links
    content_area = soup.find("main") or soup.find("div", id=re.compile(r"main|content")) or soup.find("body") or soup

    # 1. Check for standard table rows in main content
    for row in content_area.find_all("tr"):
        cells = row.find_all(["td", "th"])
        if len(cells) < 2:
            continue
        row_text = " ".join(c.get_text(strip=True) for c in cells)
        for cell in cells:
            candidate = sanitize_text(cell.get_text(strip=True))
            if is_corporate_insurer(candidate):
                reg_no = extract_reg_number(row_text) or re.sub(r"[^A-Za-z0-9]", "", candidate)[:10].upper()
                page_insurers[candidate] = {
                    "insurer_id": f"INS_{reg_no}",
                    "insurer_name": candidate,
                    "reg_number": reg_no,
                    "status": "ACTIVE"
                }

    # 2. Check for Drupal Views rows, cards, and list-items
    view_rows = content_area.find_all(["div", "article", "li"], class_=re.compile(r"(views-row|views-col|item-list|card|entity)"))
    for item in view_rows:
        text_block = item.get_text(separator=" ", strip=True)
        # Search for headings or primary anchor tags
        anchors = item.find_all(["h2", "h3", "h4", "a", "strong"])
        for a in anchors:
            candidate = sanitize_text(a.get_text(strip=True))
            if is_corporate_insurer(candidate):
                reg_no = extract_reg_number(text_block) or re.sub(r"[^A-Za-z0-9]", "", candidate)[:10].upper()
                if candidate not in page_insurers:
                    page_insurers[candidate] = {
                        "insurer_id": f"INS_{reg_no}",
                        "insurer_name": candidate,
                        "reg_number": reg_no,
                        "status": "ACTIVE"
                    }

    # 3. Fallback: Parse distinct content links inside main view
    if len(page_insurers) < 2:
        for a in content_area.find_all("a", href=True):
            candidate = sanitize_text(a.get_text(strip=True))
            if is_corporate_insurer(candidate) and candidate not in page_insurers:
                parent_text = a.parent.get_text(separator=" ", strip=True) if a.parent else ""
                reg_no = extract_reg_number(parent_text) or re.sub(r"[^A-Za-z0-9]", "", candidate)[:10].upper()
                page_insurers[candidate] = {
                    "insurer_id": f"INS_{reg_no}",
                    "insurer_name": candidate,
                    "reg_number": reg_no,
                    "status": "ACTIVE"
                }

    return page_insurers

def scrape_registered_life_insurers() -> List[Dict[str, str]]:
    logger.info("Initializing multi-page crawler on IRDAI directory...")
    session = requests.Session()
    session.mount("https://", SSLHonorAdapter())
    session.headers.update(HEADERS)

    all_insurers: Dict[str, Dict[str, str]] = {}
    
    # Direct traversal across Drupal Views pagination pages (0 to 9)
    for page_idx in range(10):
        url = BASE_IRDAI_URL if page_idx == 0 else f"{BASE_IRDAI_URL}?page={page_idx}"
        logger.info("Crawling page %d: %s", page_idx + 1, url)

        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
            if resp.status_code != 200:
                logger.info("Page %d returned status %d. Halting pagination.", page_idx + 1, resp.status_code)
                break

            soup = BeautifulSoup(resp.text, "html.parser")
            page_records = extract_entities_from_page(soup)
            
            # Check how many NEW records were found on this page
            new_records = {k: v for k, v in page_records.items() if k not in all_insurers}
            logger.info("Extracted %d items from page (%d new).", len(page_records), len(new_records))
            
            if not new_records and page_idx > 0:
                # If a page offers no new distinct records, the end of the listing has been reached
                logger.info("No new records on page %d. Ending crawl.", page_idx + 1)
                break

            all_insurers.update(new_records)

        except Exception as exc:
            logger.error("Error scraping %s: %s", url, exc)
            break

    logger.info("Crawling finished. Total unique life insurers discovered: %d", len(all_insurers))
    
    if not all_insurers:
        raise RuntimeError("IRDAI crawl completed, but zero life insurance entities were extracted.")

    return list(all_insurers.values())