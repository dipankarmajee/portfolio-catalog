"""
scrapers/irdai_scraper.py

Fully dynamic crawler for IRDAI regulated entities.
Filters placeholder/javascript anchors and traverses legitimate directory tables.
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
}


class IRDAIScraper:
    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        retries = Retry(total=3, backoff_factor=1.0, status_forcelist=[429, 500, 502, 503, 504], raise_on_status=False)
        self.session.mount("https://", HTTPAdapter(max_retries=retries))
        self.session.headers.update(HEADERS)

    @staticmethod
    def _clean_text(val: Optional[str]) -> str:
        if not val:
            return ""
        val = re.sub(r"^/\s*", "", val.strip())
        return re.sub(r"\s+", " ", val).strip()

    @staticmethod
    def _normalize_category_key(label: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9\s]", " ", label).upper()
        tokens = [t for t in cleaned.split() if t]
        return "_".join(tokens) if tokens else "REGULATED_ENTITY"

    def discover_directories(self) -> List[Tuple[str, str]]:
        logger.info("Discovering entity directories dynamically from portal root...")
        discovered: Dict[str, str] = {}

        try:
            resp = self.session.get(BASE_PORTAL, timeout=30)
            if resp.status_code != 200:
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            nav_containers = soup.find_all(["nav", "ul", "div", "header"], class_=re.compile(r"menu|nav|navbar|dropdown", re.I))
            candidates = nav_containers if nav_containers else [soup]

            indicator_pattern = re.compile(r"insurer|broker|agent|intermediar|surveyor|repository|tpa|aggregator|registered|list-of", re.I)
            exclusion_pattern = re.compile(r"tender|career|circular|contact|faq|press|annual|report|rti", re.I)

            for container in candidates:
                for a in container.find_all("a", href=True):
                    raw_href = a["href"].strip()
                    label = self._clean_text(a.get_text())

                    # Strict filter for non-routable hrefs and placeholder javascript tags
                    if not raw_href or raw_href.lower().startswith(("javascript:", "#", "mailto:", "tel:")):
                        continue
                    if raw_href in (";", "javascript:;", "javascript:void(0);"):
                        continue

                    target_url = urljoin(BASE_PORTAL, raw_href)
                    parsed = urlparse(target_url)

                    # Only accept real HTTP/HTTPS protocols
                    if parsed.scheme not in ("http", "https") or not parsed.netloc:
                        continue

                    path = parsed.path.lower()
                    if exclusion_pattern.search(path):
                        continue

                    if indicator_pattern.search(path) or indicator_pattern.search(label):
                        cat_label = label if len(label) > 3 else path.strip("/").split("/")[-1]
                        cat_key = self._normalize_category_key(cat_label)
                        if target_url not in discovered.values():
                            discovered[cat_key] = target_url

        except Exception as e:
            logger.error(f"Error during dynamic discovery: {e}")

        logger.info(f"Discovered {len(discovered)} valid HTTP directories dynamically.")
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

                headers = [self._clean_text(c.get_text()).lower() for c in rows[0].find_all(["th", "td"])]
                reg_idx = next((i for i, h in enumerate(headers) if any(k in h for k in ["reg", "sl", "sr", "code", "licence", "license"])), 0)
                name_idx = next((i for i, h in enumerate(headers) if any(k in h for k in ["name", "entity", "insurer", "company", "broker", "corporate"])), 1)
                web_idx = next((i for i, h in enumerate(headers) if any(k in h for k in ["web", "link", "url", "portal"])), None)

                records_found = 0
                for row in rows[1:]:
                    cells = row.find_all(["td", "th"])
                    if len(cells) <= max(reg_idx, name_idx):
                        continue

                    raw_reg = self._clean_text(cells[reg_idx].get_text())
                    name = self._clean_text(cells[name_idx].get_text())
                    if not name or name.lower() in ("name", "total", "description"):
                        continue

                    reg_digits = re.search(r"\d+", raw_reg)
                    reg_num = reg_digits.group(0) if reg_digits else raw_reg

                    web_url = ""
                    if web_idx is not None and len(cells) > web_idx:
                        a_tag = cells[web_idx].find("a")
                        web_url = a_tag.get("href", "") if a_tag else self._clean_text(cells[web_idx].get_text())
                    else:
                        a_tag = cells[name_idx].find("a")
                        if a_tag and a_tag.get("href"):
                            web_url = a_tag.get("href", "")

                    if web_url and not web_url.startswith("http"):
                        web_url = urljoin(BASE_PORTAL, web_url)

                    records_found += 1
                    yield {
                        "category": category,
                        "reg_number": reg_num,
                        "entity_name": name,
                        "website": web_url,
                        "source_url": current_url,
                    }

                # Follow pagination dynamically
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