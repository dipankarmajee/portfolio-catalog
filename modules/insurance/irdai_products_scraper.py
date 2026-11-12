"""
modules/insurance/irdai_products_scraper.py

Dynamically scrapes IRDAI life insurance products registry.
Primary source:  https://irdai.gov.in/list-of-products-life
Fallback source: https://www.lifeinscouncil.org/industry%20information/UINdetails.aspx

No hardcoded product lists — everything is scraped at runtime.
"""

import logging
import re
import time
from typing import Dict, Generator, List, Optional
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse

from bs4 import BeautifulSoup
from dateutil import parser as date_parser
import requests

from core.http_client import create_resilient_session
from core.text_utils import clean_english_text
from core.urls import (
    IRDAI_LIFE_PRODUCTS_LIST_URL,
    IRDAI_LIFE_PRODUCTS_ALT_URL,
    LIFE_COUNCIL_UIN_URL,
)

logger = logging.getLogger(__name__)

# UIN pattern: 3 digits, N or L, 3-4 digits, V, 2 digits — e.g. "111N1333V03", "101L063V05"
# IRDAI allows 3 or 4 digits in the middle segment.
# No word-boundary \b as UINs may abut spaces or punctuation directly.
_UIN_PATTERN = re.compile(r'(?<!\d)(\d{3}[NL]\d{3,4}V\d{2})(?!\d)')

# Category keyword mapping (checked in order; first match wins)
# IMPORTANT: "Group" must come BEFORE term/annuity so "Group Term" → "Group"
_CATEGORY_RULES: List[tuple] = [
    ("ULIP",           re.compile(r'\b(ulip|unit.?linked|linked)\b', re.I)),
    ("Group",          re.compile(r'\b(group)\b', re.I)),
    ("Term Assurance", re.compile(r'\b(term|pure.?risk|protection)\b', re.I)),
    ("Annuity",        re.compile(r'\b(annuity|pension|retirement)\b', re.I)),
    ("Endowment",      re.compile(r'\b(endowment|savings|money.?back|moneyback|guaranteed)\b', re.I)),
    ("Whole Life",     re.compile(r'\b(whole.?life)\b', re.I)),
    ("Health",         re.compile(r'\b(health|critical.?illness|hospital)\b', re.I)),
    ("Rider",          re.compile(r'\b(rider|add.?on|addon)\b', re.I)),
]

# Reasonable crawl delay between pages to be polite
_PAGE_DELAY_SECONDS = 1.5


class IRDAIProductsScraper:
    """
    Scrapes IRDAI life insurance products registry dynamically.

    Usage::

        scraper = IRDAIProductsScraper()
        for product in scraper.scrape_all_products():
            print(product)
    """

    def __init__(self, session: Optional[requests.Session] = None):
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://irdai.gov.in/",
        }
        self.session = session or create_resilient_session(headers=headers)

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_uin(text: str) -> Optional[str]:
        """Extract IRDAI UIN from arbitrary text. Returns the first match or None."""
        if not text:
            return None
        m = _UIN_PATTERN.search(text)
        return m.group(1) if m else None

    @staticmethod
    def _classify_category(text: str) -> str:
        """Derive product category from product name / type text."""
        if not text:
            return "Other"
        for category, pattern in _CATEGORY_RULES:
            if pattern.search(text):
                return category
        return "Other"

    @staticmethod
    def _parse_date(raw: str) -> Optional[str]:
        """Parse a date string to YYYY-MM-DD. Returns None if unparseable."""
        if not raw:
            return None
        raw = raw.strip()
        if not raw or raw.lower() in ("na", "n/a", "-", "--", "null", ""):
            return None
        try:
            return date_parser.parse(raw, dayfirst=True).strftime("%Y-%m-%d")
        except (ValueError, OverflowError, TypeError):
            return None

    # ------------------------------------------------------------------
    # IRDAI primary scraper
    # ------------------------------------------------------------------

    def _fetch_page(self, url: str, timeout: int = 30) -> Optional[BeautifulSoup]:
        """Fetch a URL and return a BeautifulSoup, or None on failure."""
        try:
            resp = self.session.get(url, timeout=timeout)
            if resp.status_code == 200:
                return BeautifulSoup(resp.text, "html.parser")
            logger.warning("HTTP %d for %s", resp.status_code, url)
            return None
        except Exception as exc:
            logger.warning("Fetch error for %s: %s", url, exc)
            return None

    def _find_next_page_url(self, soup: BeautifulSoup, current_url: str) -> Optional[str]:
        """
        Detect pagination and return the next-page URL, or None if last page.
        Handles:
          - Liferay delta/page parameter URLs  (?..._cur=N&...)
          - Generic rel="next" link tags
          - Text links labelled "next", "»", "›", ">", "Next Page"
          - ASP.NET __EVENTARGUMENT-style postbacks (not followed here, but detected)
        """
        base = current_url

        # 1. Explicit <link rel="next"> or <a rel="next">
        for tag in soup.find_all(["link", "a"], rel=lambda r: r and "next" in (r if isinstance(r, list) else [r])):
            href = tag.get("href", "")
            if href:
                return urljoin(base, href)

        # 2. Anchor tags whose visible text looks like "next"
        next_patterns = re.compile(r'^(next|»|›|>|next\s*page|\d+\s*>)$', re.I)
        for a in soup.find_all("a", href=True):
            txt = a.get_text(strip=True)
            if next_patterns.match(txt):
                href = a.get("href", "")
                if href and href != "#":
                    return urljoin(base, href)

        # 3. Liferay-style _cur / delta pagination in query string
        # Look for a page link that increments the current page number
        parsed = urlparse(current_url)
        qs = parse_qs(parsed.query, keep_blank_values=True)
        cur_key = next(
            (k for k in qs if k.endswith("_cur") or k == "page" or k == "p"), None
        )
        if cur_key:
            try:
                current_page = int(qs[cur_key][0])
                # Verify we can find a link that points to current_page+1
                next_page = current_page + 1
                next_page_links = soup.find_all("a", href=True)
                for a in next_page_links:
                    href = a.get("href", "")
                    if f"_cur={next_page}" in href or f"page={next_page}" in href:
                        return urljoin(base, href)
            except (ValueError, IndexError):
                pass

        # 4. Scan all pagination links and find the one after the active/current
        pager = soup.find(["ul", "div", "nav"], class_=re.compile(r'pag(e|ination|er)', re.I))
        if pager:
            links = pager.find_all("a", href=True)
            active = pager.find(["span", "li", "a"], class_=re.compile(r'active|current|selected', re.I))
            if active and links:
                try:
                    active_txt = active.get_text(strip=True)
                    for i, a in enumerate(links):
                        if a.get_text(strip=True) == active_txt and i + 1 < len(links):
                            href = links[i + 1].get("href", "")
                            if href and href != "#":
                                return urljoin(base, href)
                except Exception:
                    pass

        return None

    def _parse_irdai_table(
        self, soup: BeautifulSoup
    ) -> List[Dict]:
        """
        Parse product rows from an HTML table on the IRDAI products page.
        Returns a list of raw product dicts.
        """
        products = []

        # Find all tables; pick the one most likely to contain product data
        tables = soup.find_all("table")
        best_table = None
        best_score = 0
        for tbl in tables:
            rows = tbl.find_all("tr")
            if len(rows) < 2:
                continue
            header_text = " ".join(
                th.get_text(" ", strip=True).lower()
                for th in (rows[0].find_all(["th", "td"]) or [])
            )
            score = sum(1 for kw in ("uin", "product", "insur", "name", "status", "date")
                        if kw in header_text)
            if score > best_score:
                best_score = score
                best_table = tbl

        if best_table is None:
            # Try a broader scan: look for any table with UIN-like data in cells
            for tbl in tables:
                text = tbl.get_text(" ")
                if _UIN_PATTERN.search(text):
                    best_table = tbl
                    break

        if best_table is None:
            logger.debug("No suitable table found on IRDAI page.")
            return products

        rows = best_table.find_all("tr")
        if not rows:
            return products

        # Map headers
        header_cells = rows[0].find_all(["th", "td"])
        headers = [c.get_text(" ", strip=True).lower() for c in header_cells]

        idx: Dict[str, int] = {}
        for i, h in enumerate(headers):
            if "uin" in h and "idx" not in idx.get("uin", "X"):
                idx.setdefault("uin", i)
            if any(w in h for w in ("product name", "plan name", "policy name", "product")):
                idx.setdefault("product_name", i)
            if any(w in h for w in ("insurer", "company", "life insurance")):
                idx.setdefault("insurer_name", i)
            if any(w in h for w in ("category", "type", "plan type")):
                idx.setdefault("category", i)
            if "status" in h or "withdrawn" in h:
                idx.setdefault("status", i)
            if any(w in h for w in ("date", "approval", "launch")):
                idx.setdefault("launch_date", i)

        for row in rows[1:]:
            cells = [td.get_text(" ", strip=True) for td in row.find_all(["td", "th"])]
            if not cells:
                continue

            # Try to extract UIN from designated column or scan all cells
            uin = None
            if "uin" in idx and idx["uin"] < len(cells):
                uin = self._parse_uin(cells[idx["uin"]])
            if not uin:
                # Scan all cells for a UIN
                for cell_text in cells:
                    uin = self._parse_uin(cell_text)
                    if uin:
                        break
            if not uin:
                continue  # Skip rows without a valid UIN

            product_name = ""
            if "product_name" in idx and idx["product_name"] < len(cells):
                product_name = clean_english_text(cells[idx["product_name"]])
            if not product_name:
                # Try to pick the longest non-UIN cell as the name
                candidates = [
                    clean_english_text(c) for c in cells
                    if not _UIN_PATTERN.search(c) and len(c) > 5
                ]
                product_name = max(candidates, key=len) if candidates else ""

            insurer_name = ""
            if "insurer_name" in idx and idx["insurer_name"] < len(cells):
                insurer_name = clean_english_text(cells[idx["insurer_name"]])

            raw_category = ""
            if "category" in idx and idx["category"] < len(cells):
                raw_category = cells[idx["category"]]

            category = self._classify_category(raw_category or product_name)

            status = "ACTIVE"
            if "status" in idx and idx["status"] < len(cells):
                raw_status = cells[idx["status"]].upper()
                if "WITHDRAW" in raw_status or "LAPSE" in raw_status or "CANCEL" in raw_status:
                    status = "WITHDRAWN"

            launch_date = None
            if "launch_date" in idx and idx["launch_date"] < len(cells):
                launch_date = self._parse_date(cells[idx["launch_date"]])

            products.append({
                "uin": uin,
                "product_name": product_name,
                "insurer_name": insurer_name,
                "category": category,
                "status": status,
                "launch_date": launch_date,
            })

        return products

    def _scrape_irdai_primary(self, base_url: str) -> Generator[Dict, None, None]:
        """
        Paginate through the IRDAI life products list and yield product dicts.
        """
        url: Optional[str] = base_url
        page_num = 1
        seen_uins: set = set()

        while url:
            logger.info("Fetching IRDAI products page %d: %s", page_num, url)
            soup = self._fetch_page(url)
            if soup is None:
                logger.warning("Could not fetch page %d; stopping pagination.", page_num)
                break

            products = self._parse_irdai_table(soup)
            if not products:
                logger.info("No products found on page %d; ending pagination.", page_num)
                break

            new_on_page = 0
            for p in products:
                if p["uin"] not in seen_uins:
                    seen_uins.add(p["uin"])
                    new_on_page += 1
                    yield p

            logger.info("Page %d: %d new products (total seen: %d).", page_num, new_on_page, len(seen_uins))

            if new_on_page == 0:
                # All products on this page were already seen — stop pagination
                break

            next_url = self._find_next_page_url(soup, url)
            if not next_url or next_url == url:
                break

            url = next_url
            page_num += 1
            time.sleep(_PAGE_DELAY_SECONDS)

    # ------------------------------------------------------------------
    # Life Insurance Council fallback scraper
    # ------------------------------------------------------------------

    def _scrape_life_council_fallback(self) -> Generator[Dict, None, None]:
        """
        Fallback: scrape UIN details from Life Insurance Council ASP.NET portal.
        Handles ASP.NET postback pagination via __EVENTARGUMENT.
        """
        logger.info("Attempting fallback scrape from Life Insurance Council UIN portal.")
        try:
            resp = self.session.get(LIFE_COUNCIL_UIN_URL, timeout=30)
            resp.raise_for_status()
        except Exception as exc:
            logger.error("Life Council UIN portal unreachable: %s", exc)
            return

        soup = BeautifulSoup(resp.text, "html.parser")
        seen_uins: set = set()

        # Extract ASP.NET hidden fields for postback
        def _get_aspnet_tokens(s: BeautifulSoup) -> Dict[str, str]:
            tokens = {}
            for inp in s.find_all("input", type="hidden"):
                name = inp.get("name") or inp.get("id", "")
                if name:
                    tokens[name] = inp.get("value", "")
            return tokens

        form = soup.find("form")
        post_url = urljoin(LIFE_COUNCIL_UIN_URL, form.get("action", "")) if form else LIFE_COUNCIL_UIN_URL

        def _parse_and_yield(s: BeautifulSoup):
            for p in self._parse_irdai_table(s):
                if p["uin"] not in seen_uins:
                    seen_uins.add(p["uin"])
                    yield p

        yield from _parse_and_yield(soup)

        # Detect page-count / "Page X of Y" pattern
        page_info = soup.find(string=re.compile(r'page\s+\d+\s+of\s+\d+', re.I))
        total_pages = 1
        if page_info:
            m = re.search(r'page\s+(\d+)\s+of\s+(\d+)', str(page_info), re.I)
            if m:
                total_pages = int(m.group(2))

        for page_num in range(2, total_pages + 1):
            tokens = _get_aspnet_tokens(soup)
            payload = {
                **tokens,
                "__EVENTTARGET": "GridView1",
                "__EVENTARGUMENT": f"Page${page_num}",
            }
            try:
                resp = self.session.post(post_url, data=payload, timeout=30)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "html.parser")
                yield from _parse_and_yield(soup)
                time.sleep(_PAGE_DELAY_SECONDS)
            except Exception as exc:
                logger.error("Life Council page %d error: %s", page_num, exc)
                break

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def scrape_all_products(self) -> Generator[Dict, None, None]:
        """
        Main generator: yields product dicts from IRDAI life products registry.

        Tries primary URL first, then alt URL, then Life Council fallback.
        Fields per product:
            uin, product_name, insurer_name, category, status, launch_date
        """
        primary_yielded = 0

        # Try primary URL
        for product in self._scrape_irdai_primary(IRDAI_LIFE_PRODUCTS_LIST_URL):
            primary_yielded += 1
            yield product

        # Try alternate URL if primary yielded nothing
        if primary_yielded == 0:
            logger.info(
                "Primary IRDAI URL yielded 0 products; trying alternate URL: %s",
                IRDAI_LIFE_PRODUCTS_ALT_URL,
            )
            for product in self._scrape_irdai_primary(IRDAI_LIFE_PRODUCTS_ALT_URL):
                primary_yielded += 1
                yield product

        # Fallback to Life Insurance Council if IRDAI scrape failed
        if primary_yielded == 0:
            logger.warning(
                "Both IRDAI URLs yielded 0 products. Falling back to Life Insurance Council."
            )
            yield from self._scrape_life_council_fallback()
