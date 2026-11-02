"""
scrapers/irdai_scraper.py
"""

import logging
import re
from typing import Dict, Generator, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

BASE_PORTAL = "https://irdai.gov.in"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


class IRDAIScraper:
    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        retries = Retry(total=3, backoff_factor=1.0, status_forcelist=[429, 500, 502, 503, 504], raise_on_status=False)
        self.session.mount("https://", HTTPAdapter(max_retries=retries))
        self.session.headers.update(HEADERS)
        self.session.cookies.set("language", "en_US")

    @staticmethod
    def _clean_english_text(val: Optional[str]) -> str:
        """Strips Hindi/Devanagari characters and formats clean English text."""
        if not val:
            return ""
        cleaned = re.sub(r"[\u0900-\u097F]+", " ", val)
        cleaned = re.sub(r"^/\s*", "", cleaned.strip())
        return re.sub(r"\s+", " ", cleaned).strip()

    @staticmethod
    def _normalize_category_key(label: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9\s]", " ", label).upper()
        tokens = [t for t in cleaned.split() if t]
        return "_".join(tokens) if tokens else "REGULATED_ENTITY"

    def discover_directories(self) -> List[Tuple[str, str]]:
        logger.info("Discovering financial entity directories dynamically from portal root...")
        discovered: Dict[str, str] = {}

        try:
            resp = self.session.get(BASE_PORTAL, timeout=30)
            if resp.status_code != 200:
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            nav_containers = soup.find_all(["nav", "ul", "div", "header"], class_=re.compile(r"menu|nav|navbar|dropdown", re.I))
            candidates = nav_containers if nav_containers else [soup]

            target_pattern = re.compile(
                r"(?:list-of-)?(?:life|general|health|non-life|re)?insurers?|brokers?|corporate-agents?|web-aggregators?|insurance-repositor(?:y|ies)",
                re.I
            )
            noise_pattern = re.compile(
                r"surveyor|holiday|tpa|requirement|fee|lapsed|gro|ombudsman|tender|career|circular|annual-report|rti|faq|press|contact|guideline|penalty|document-detail|order|advisory|noc\.",
                re.I
            )

            for container in candidates:
                for a in container.find_all("a", href=True):
                    raw_href = a["href"].strip()
                    label = self._clean_english_text(a.get_text())

                    if not raw_href or raw_href.lower().startswith(("javascript:", "#", "mailto:", "tel:")):
                        continue
                    if raw_href in (";", "javascript:;", "javascript:void(0);"):
                        continue

                    target_url = urljoin(BASE_PORTAL, raw_href)
                    parsed = urlparse(target_url)

                    # Restrict to irdai.gov.in host and exclude document endpoints/files
                    if parsed.scheme not in ("http", "https") or parsed.netloc != "irdai.gov.in":
                        continue
                    if any(ext in parsed.path.lower() for ext in [".pdf", ".xlsx", ".docx", ".zip"]):
                        continue

                    path = parsed.path.lower()
                    if noise_pattern.search(path) or noise_pattern.search(label) or any(k in path for k in ["/hi/", "/hindi/"]):
                        continue

                    if target_pattern.search(path) or target_pattern.search(label):
                        cat_key = self._normalize_category_key(label) if len(label) > 3 else path.strip("/").split("/")[-1].upper().replace("-", "_")
                        if target_url not in discovered.values():
                            discovered[cat_key] = target_url

        except Exception as e:
            logger.error(f"Error during dynamic discovery: {e}")

        logger.info(f"Discovered {len(discovered)} valid financial entity directories.")
        return list(discovered.items())

    def scrape_directory(self, category: str, url: str) -> Generator[Dict[str, str], None, None]:
        current_url = url
        while current_url:
            parsed = urlparse(current_url)
            if parsed.scheme not in ("http", "https"):
                break

            try:
                resp = self.session.get(current_url, timeout=30)
                if resp.status_code != 200:
                    break

                soup = BeautifulSoup(resp.text, "html.parser")
                tables = soup.find_all("table")
                if not tables:
                    break

                table = max(tables, key=lambda t: len(t.find_all("tr")))
                rows = table.find_all("tr")
                if len(rows) < 2:
                    break

                headers = [self._clean_english_text(c.get_text()).lower() for c in rows[0].find_all(["th", "td"])]
                reg_idx = next((i for i, h in enumerate(headers) if any(k in h for k in ["reg", "sl", "sr", "code", "licence", "license"])), 0)
                name_idx = next((i for i, h in enumerate(headers) if any(k in h for k in ["name", "entity", "insurer", "company", "broker", "corporate"])), 1)

                records_found = 0
                for row in rows[1:]:
                    cells = row.find_all(["td", "th"])
                    if len(cells) <= max(reg_idx, name_idx):
                        continue

                    raw_reg = self._clean_english_text(cells[reg_idx].get_text())
                    raw_name = cells[name_idx].get_text()
                    clean_name = self._clean_english_text(raw_name)

                    if not clean_name or clean_name.lower() in ("name", "total", "description"):
                        continue

                    # 1. Direct regex URL discovery across raw text and HTML of all cells in this row
                    row_raw_text = " | ".join(c.get_text() for c in cells)
                    found_urls = re.findall(r"https?://[^\s<>\"\'|]+", row_raw_text)
                    valid_urls = [u.rstrip("/,.;)") for u in found_urls if "irdai.gov.in" not in u]
                    web_url = valid_urls[0] if valid_urls else ""

                    # 2. Check <a> href attributes if not found in text
                    if not web_url:
                        for c in cells:
                            for a in c.find_all("a", href=True):
                                href = a["href"].strip()
                                if href.startswith("http") and "irdai.gov.in" not in href:
                                    web_url = href.rstrip("/,.;)")
                                    break
                            if web_url:
                                break

                    # 3. Fallback: Extract from registered email domain if URL is not explicitly printed
                    if not web_url:
                        email_matches = re.findall(r"@([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", row_raw_text)
                        for domain in email_matches:
                            clean_domain = domain.lower().lstrip("www.")
                            if clean_domain not in ("gmail.com", "yahoo.com", "outlook.com", "gov.in"):
                                web_url = f"https://www.{clean_domain}"
                                break

                    reg_digits = re.search(r"\d+", raw_reg)
                    reg_num = reg_digits.group(0) if reg_digits else raw_reg

                    records_found += 1
                    yield {
                        "category": category,
                        "reg_number": reg_num,
                        "entity_name": clean_name,
                        "website": web_url,
                        "source_url": current_url,
                    }

                # Follow pagination
                next_url = None
                for a in soup.find_all("a", href=True):
                    txt = a.get_text().strip().lower()
                    rel = a.get("rel", "")
                    raw_href = a["href"].strip()
                    if raw_href and not raw_href.lower().startswith("javascript:"):
                        if "next" in txt or "next" in rel or txt in (">", "»"):
                            candidate = urljoin(BASE_PORTAL, raw_href)
                            if urlparse(candidate).scheme in ("http", "https"):
                                next_url = candidate
                                break

                if next_url and next_url != current_url and records_found > 0:
                    current_url = next_url
                else:
                    current_url = None

            except Exception as e:
                logger.error(f"Error scraping {category} from {current_url}: {e}")
                break

    def scrape_all(self) -> Generator[Dict[str, str], None, None]:
        directories = self.discover_directories()
        seen: Set[Tuple[str, str, str]] = set()

        for category, url in directories:
            for item in self.scrape_directory(category, url):
                key = (item["category"], item["reg_number"], item["entity_name"])
                if key not in seen:
                    seen.add(key)
                    yield item