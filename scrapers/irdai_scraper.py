"""
Module: scrapers.irdai_scraper
Purpose: 100% Dynamic crawler discovering and extracting all IRDAI regulated entities across all pages.
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
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] [IRDAI_CRAWLER] %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

BASE_PORTAL_URL = "https://irdai.gov.in"
SEED_URL = "https://irdai.gov.in/life-insurers1"
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

def sanitize_english_text(raw_text: str) -> str:
    """Extracts and normalizes English text from mixed Hindi-English cells."""
    cleaned = " ".join(raw_text.split()).strip()
    english_segments = re.findall(r"[A-Za-z0-9\s\.\,\-\(\)\&\/\:\@]+", cleaned)
    candidate = " ".join(" ".join(english_segments).split()).strip()
    return candidate if candidate else cleaned

def clean_company_name(name_raw: str) -> str:
    cleaned = sanitize_english_text(name_raw)
    for sep in ["Tel:", "Phone:", "Email:", "Address:", "Fax:", "CIN:", "Website:"]:
        if sep in cleaned:
            cleaned = cleaned.split(sep)[0].strip()
    return cleaned

def discover_regulated_entity_sections(session: requests.Session) -> Dict[str, str]:
    """
    100% Dynamic discovery: Scrapes all child links under Regulated Entities
    from the portal navigation. Zero hardcoded dictionary defaults.
    """
    logger.info("Discovering Regulated Entities sections dynamically from %s...", SEED_URL)
    sections: Dict[str, str] = {}
    
    resp = session.get(SEED_URL, timeout=REQUEST_TIMEOUT)
    if resp.status_code != 200:
        raise RuntimeError(f"Failed to access seed URL {SEED_URL} (HTTP {resp.status_code})")

    soup = BeautifulSoup(resp.text, "html.parser")
    
    # Extract links that represent directory listings under Regulated Entities
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        text = " ".join(a.get_text().split()).strip()
        
        # Match entity links and skip informational guidelines / javascript links
        is_entity_href = any(k in href for k in ["-insurers", "reinsurer", "broker", "corporate-agent", "telemarketer"])
        is_informational = any(k in href for k in ["about-", "requirements-", "lapsed-", "guidelines"])
        
        if is_entity_href and not is_informational and not href.startswith("javascript:") and len(text) > 3:
            full_url = urljoin(BASE_PORTAL_URL, href)
            cat_key = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").upper()
            
            # Keep unique categories and avoid duplicate URLs
            if cat_key not in sections and full_url not in sections.values():
                sections[cat_key] = full_url

    logger.info("Dynamically discovered %d distinct entity sections: %s", len(sections), list(sections.keys()))
    
    if not sections:
        raise RuntimeError("Dynamic menu discovery completed but found 0 entity sections.")

    return sections

def parse_table_page(soup: BeautifulSoup, category: str, page_url: str) -> List[Dict[str, str]]:
    """Extracts entities from tables on a single page."""
    entities = []
    tables = soup.find_all("table")

    for table in tables:
        for tr in table.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if len(cells) < 2:
                continue

            cell_texts = [" ".join(c.get_text().split()).strip() for c in cells]
            
            # Detect registration number
            reg_candidate = None
            for txt in cell_texts:
                match = re.search(r"\b(1\d\d|[2-5]\d\d|\d{2,6}|[A-Z0-9\/\-]{4,15})\b", txt)
                # Pure numbers or official statutory formats
                if re.match(r"^\d{1,4}$", txt) and int(txt) > 0 and int(txt) < 1000:
                    reg_candidate = txt
                    break

            # Detect company name
            name_candidate = None
            for txt in cell_texts:
                eng = clean_company_name(txt)
                # Match company designations or entity titles
                if len(eng) > 6 and any(term in eng.lower() for term in ["insurance", "assurance", "corporation", "ltd", "limited", "broker", "reinsurance", "co."]):
                    name_candidate = eng
                    break

            # Fallback name selection from non-numeric text
            if not name_candidate:
                non_num_candidates = [clean_company_name(t) for t in cell_texts if len(clean_company_name(t)) > 6 and not re.match(r"^[\d\s\-\/\.]+$", t)]
                if non_num_candidates:
                    name_candidate = non_num_candidates[0]

            # Detect website
            website_url = ""
            for a in tr.find_all("a", href=True):
                if a["href"].startswith("http"):
                    website_url = a["href"].strip()
                    break

            if name_candidate:
                clean_reg = reg_candidate if reg_candidate else re.sub(r"[^A-Za-z0-9]", "", name_candidate)[:10].upper()
                entities.append({
                    "entity_id": f"ENT_{clean_reg}",
                    "entity_name": name_candidate,
                    "reg_number": clean_reg,
                    "category": category,
                    "website": website_url,
                    "source_url": page_url,
                    "status": "ACTIVE"
                })

    return entities

def scrape_all_regulated_entities() -> List[Dict[str, str]]:
    """Crawls all discovered categories across all pages."""
    session = requests.Session()
    session.mount("https://", SSLHonorAdapter())
    session.headers.update(HEADERS)

    sections = discover_regulated_entity_sections(session)
    all_discovered: Dict[str, Dict[str, str]] = {}

    for cat_name, cat_url in sections.items():
        logger.info("--- Crawling Category: %s (%s) ---", cat_name, cat_url)
        page_idx = 0
        consecutive_empty = 0

        while page_idx < 15:  # Maximum 15 pages per category guardrail
            p_url = cat_url if page_idx == 0 else f"{cat_url}?page={page_idx}"
            try:
                resp = session.get(p_url, timeout=REQUEST_TIMEOUT)
                if resp.status_code != 200:
                    break

                soup = BeautifulSoup(resp.text, "html.parser")
                page_entities = parse_table_page(soup, cat_name, p_url)

                new_count = 0
                for item in page_entities:
                    unique_key = f"{cat_name}_{item['reg_number']}_{item['entity_name']}"
                    if unique_key not in all_discovered:
                        all_discovered[unique_key] = item
                        new_count += 1

                logger.info("Category %s [Page %d]: Extracted %d entities (%d new).", cat_name, page_idx + 1, len(page_entities), new_count)

                if new_count == 0:
                    logger.info("Page %d yielded 0 new entities. Moving to next category.", page_idx + 1)
                        break
                else:
                    consecutive_empty = 0

            except Exception as exc:
                logger.error("Error reading %s: %s", p_url, exc)
                break

            page_idx += 1

    logger.info("Total regulated entities extracted dynamically: %d", len(all_discovered))
    return list(all_discovered.values())

def scrape_registered_life_insurers() -> List[Dict[str, str]]:
    """Compatibility adapter for sync_insurers_ulips.py returning Life Insurers."""
    all_entities = scrape_all_regulated_entities()
    life_insurers = [
        {
            "insurer_id": f"INS_{e['reg_number']}",
            "insurer_name": e["entity_name"],
            "reg_number": e["reg_number"],
            "category": e["category"],
            "website": e["website"],
            "source_url": e["source_url"],
            "status": e["status"]
        }
        for e in all_entities if "LIFE" in e["category"]
    ]
    logger.info("Filtered %d Life Insurer corporate records for master_insurers.", len(life_insurers))
    return life_insurers