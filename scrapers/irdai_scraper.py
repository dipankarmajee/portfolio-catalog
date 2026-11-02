"""
Module: scrapers.irdai_scraper
Purpose: 100% Dynamic, paginated scraper for official IRDAI Life Insurers directory.
Filters out statutory councils/associations while preserving all commercial life insurers.
"""

import logging
import sys
import re
from typing import List, Dict, Set
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

def is_life_insurer(name: str) -> bool:
    if len(name) < 7 or len(name) > 120:
        return False
    lower = name.lower()

    # Must be a corporate entity
    has_life = "life" in lower or "lic" in lower
    has_corp = any(term in lower for term in ["insurance", "assurance", "corporation", "ltd", "limited", "company"])
    
    # Exclude regulatory bodies, councils, portals, and UI navigation links
    is_excluded = any(term in lower for term in [
        "council", "association", "ombudsman", "authority", "forum",
        "types of", "about us", "regulations", "circulars", "guidelines",
        "consumer education", "grievance", "public notice", "overview", "committee"
    ])

    return has_life and has_corp and not is_excluded

def extract_entities_from_soup(soup: BeautifulSoup) -> Dict[str, Dict[str, str]]:
    page_insurers: Dict[str, Dict[str, str]] = {}

    # 1. Search Tables
    for row in soup.find_all("tr"):
        cells = row.find_all(["td", "th"])
        if len(cells) < 2:
            continue
        row_text = " ".join(c.get_text(strip=True) for c in cells)
        for cell in cells:
            candidate = sanitize_text(cell.get_text(strip=True))
            if is_life_insurer(candidate):
                reg_match = re.search(r"(?:reg(?:istration)?\.?\s*(?:no\.?)?[:\s]*)?\b(1\d\d|[2-5]\d\d)\b", row_text, re.IGNORECASE)
                reg_no = reg_match.group(1) if reg_match else re.sub(r"[^A-Za-z0-9]", "", candidate)[:10].upper()
                page_insurers[candidate] = {
                    "insurer_id": f"INS_{reg_no}",
                    "insurer_name": candidate,
                    "reg_number": reg_no,
                    "status": "ACTIVE"
                }

    # 2. Search Semantic Cards & Views Rows
    containers = soup.find_all(["div", "article", "li"], class_=re.compile(r"(views-row|field-content|item|card|entity)"))
    for container in containers:
        container_text = container.get_text(separator=" ", strip=True)
        anchors = container.find_all(["a", "h2", "h3", "h4", "strong"])
        for tag in anchors:
            candidate = sanitize_text(tag.get_text(strip=True))
            if is_life_insurer(candidate):
                reg_match = re.search(r"(?:reg(?:istration)?\.?\s*(?:no\.?)?[:\s]*)?\b(1\d\d|[2-5]\d\d)\b", container_text, re.IGNORECASE)
                reg_no = reg_match.group(1) if reg_match else re.sub(r"[^A-Za-z0-9]", "", candidate)[:10].upper()
                if candidate not in page_insurers:
                    page_insurers[candidate] = {
                        "insurer_id": f"INS_{reg_no}",
                        "insurer_name": candidate,
                        "reg_number": reg_no,
                        "status": "ACTIVE"
                    }

    # 3. Direct Anchor Search
    if not page_insurers:
        for a in soup.find_all("a"):
            candidate = sanitize_text(a.get_text(strip=True))
            if is_life_insurer(candidate) and candidate not in page_insurers:
                parent = a.find_parent(["div", "li", "tr", "section"])
                parent_text = parent.get_text(separator=" ", strip=True) if parent else ""
                reg_match = re.search(r"(?:reg(?:istration)?\.?\s*(?:no\.?)?[:\s]*)?\b(1\d\d|[2-5]\d\d)\b", parent_text, re.IGNORECASE)
                reg_no = reg_match.group(1) if reg_match else re.sub(r"[^A-Za-z0-9]", "", candidate)[:10].upper()
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
    visited_urls: Set[str] = set()
    urls_to_visit = [BASE_IRDAI_URL]

    page_idx = 0
    max_pages = 10

    while urls_to_visit and page_idx < max_pages:
        current_url = urls_to_visit.pop(0)
        if current_url in visited_urls:
            continue
        visited_urls.add(current_url)
        page_idx += 1

        logger.info("Crawling page %d: %s", page_idx, current_url)
        try:
            resp = session.get(current_url, timeout=REQUEST_TIMEOUT)
            if resp.status_code != 200:
                logger.warning("HTTP %d received for %s. Skipping page.", resp.status_code, current_url)
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            page_records = extract_entities_from_soup(soup)
            new_records = {k: v for k, v in page_records.items() if k not in all_insurers}
            logger.info("Extracted %d items from page (%d new).", len(page_records), len(new_records))

            if not new_records and page_idx > 1:
                logger.info("No new records on page %d. Ending crawl.", page_idx)
                break

            all_insurers.update(new_records)

            # Discover pagination links
            pagination_nav = soup.find(["ul", "nav", "div"], class_=re.compile(r"(pager|pagination)"))
            if pagination_nav:
                for link in pagination_nav.find_all("a", href=True):
                    next_href = link["href"]
                    full_url = urljoin(BASE_IRDAI_URL, next_href)
                    if full_url not in visited_urls and "page=" in full_url:
                        urls_to_visit.append(full_url)
            else:
                if page_idx == 1 and len(page_records) > 0:
                    for p in range(1, 5):
                        p_url = f"{BASE_IRDAI_URL}?page={p}"
                        if p_url not in visited_urls:
                            urls_to_visit.append(p_url)

        except Exception as exc:
            logger.error("Error scraping page %s: %s", current_url, exc)

    logger.info("Crawling finished. Total unique life insurers discovered: %d", len(all_insurers))

    if not all_insurers:
        raise RuntimeError("IRDAI crawl completed, but zero life insurance entities were extracted.")

    return list(all_insurers.values())