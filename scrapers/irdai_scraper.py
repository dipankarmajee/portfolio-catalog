"""
Module: scrapers.irdai_scraper
Purpose: 100% Dynamic scraper for official Life Insurers directory.
Targets official entity listings and filters out article links and councils.
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

TARGET_URLS = [
    "https://irdai.gov.in/life-insurers",
    "https://irdai.gov.in/list-of-life-insurers",
    "https://www.lifeinscouncil.org/members_directory"
]

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

def is_commercial_life_insurer(name: str) -> bool:
    """
    Validates that the string is an actual commercial life insurance enterprise,
    not an article title, product guideline, or committee.
    """
    if len(name) < 10 or len(name) > 100:
        return False
    lower = name.lower()

    # Must contain life insurance/assurance designation or LIC
    has_life = ("life" in lower and any(term in lower for term in ["insurance", "assurance"])) or "life insurance corporation" in lower
    if not has_life:
        return False

    # Must be a commercial corporate entity
    has_corp_suffix = any(term in lower for term in ["limited", "ltd", "corporation of india", "co. ltd"])
    if not has_corp_suffix:
        return False

    # Exclude administrative bodies, consumer guidelines, and UI links
    is_noise = any(term in lower for term in [
        "council", "association", "ombudsman", "authority", "products",
        "terms and conditions", "guidelines", "circular", "regulations",
        "consumer", "overview", "types of", "about us", "clause", "handbook"
    ])
    return not is_noise

def extract_reg_number(text: str) -> str:
    match = re.search(r"(?:reg(?:istration)?\.?\s*(?:no\.?)?[:\s]*)?\b(1\d\d|[2-5]\d\d)\b", text, re.IGNORECASE)
    if match:
        return match.group(1)
    return ""

def scrape_registered_life_insurers() -> List[Dict[str, str]]:
    logger.info("Initializing statutory life insurers scraper...")
    session = requests.Session()
    session.mount("https://", SSLHonorAdapter())
    session.headers.update(HEADERS)

    discovered_insurers: Dict[str, Dict[str, str]] = {}

    for target_url in TARGET_URLS:
        logger.info("Checking directory endpoint: %s", target_url)
        try:
            resp = session.get(target_url, timeout=REQUEST_TIMEOUT)
            if resp.status_code != 200:
                logger.info("Endpoint %s returned HTTP %d, checking next...", target_url, resp.status_code)
                continue

            soup = BeautifulSoup(resp.text, "html.parser")

            # 1. Inspect Table Structures (standard layout on registry portals)
            for row in soup.find_all("tr"):
                cells = row.find_all(["td", "th"])
                if len(cells) < 2:
                    continue
                row_text = " ".join(c.get_text(strip=True) for c in cells)
                for cell in cells:
                    candidate = sanitize_text(cell.get_text(strip=True))
                    if is_commercial_life_insurer(candidate):
                        reg_no = extract_reg_number(row_text) or re.sub(r"[^A-Za-z0-9]", "", candidate)[:10].upper()
                        discovered_insurers[candidate] = {
                            "insurer_id": f"INS_{reg_no}",
                            "insurer_name": candidate,
                            "reg_number": reg_no,
                            "status": "ACTIVE"
                        }

            # 2. Inspect Drupal View Grid / Row Containers
            for item in soup.find_all(["div", "article", "li"], class_=re.compile(r"(views-row|views-col|card|entity|field-content)")):
                text_block = item.get_text(separator=" ", strip=True)
                for tag in item.find_all(["a", "h2", "h3", "h4", "strong"]):
                    candidate = sanitize_text(tag.get_text(strip=True))
                    if is_commercial_life_insurer(candidate):
                        reg_no = extract_reg_number(text_block) or re.sub(r"[^A-Za-z0-9]", "", candidate)[:10].upper()
                        if candidate not in discovered_insurers:
                            discovered_insurers[candidate] = {
                                "insurer_id": f"INS_{reg_no}",
                                "insurer_name": candidate,
                                "reg_number": reg_no,
                                "status": "ACTIVE"
                            }

            # 3. Direct anchor parse across content section
            main_block = soup.find("main") or soup.find("div", id=re.compile(r"content|main")) or soup
            for a in main_block.find_all("a"):
                candidate = sanitize_text(a.get_text(strip=True))
                if is_commercial_life_insurer(candidate) and candidate not in discovered_insurers:
                    parent_text = a.parent.get_text(separator=" ", strip=True) if a.parent else ""
                    reg_no = extract_reg_number(parent_text) or re.sub(r"[^A-Za-z0-9]", "", candidate)[:10].upper()
                    discovered_insurers[candidate] = {
                        "insurer_id": f"INS_{reg_no}",
                        "insurer_name": candidate,
                        "reg_number": reg_no,
                        "status": "ACTIVE"
                    }

            logger.info("Found %d valid life insurer corporations from %s", len(discovered_insurers), target_url)
            if len(discovered_insurers) >= 20:
                break

        except Exception as exc:
            logger.warning("Error fetching %s: %s", target_url, exc)

    logger.info("Total validated life insurers discovered: %d", len(discovered_insurers))

    if not discovered_insurers:
        raise RuntimeError("No life insurance companies matched corporate validation criteria.")

    return list(discovered_insurers.values())