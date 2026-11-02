"""
scrapers/life_council_scraper.py

Automated dynamic extractor for Indian ULIP Fund NAVs from the
Life Insurance Council ASP.NET portal.
"""

import logging
import re
from typing import Dict, Generator, List, Optional, Tuple
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dateutil import parser as date_parser
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

PORTAL_URL = "https://www.lifeinscouncil.org/industry%20information/list_of_fund_NAVs.aspx"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Origin": "https://www.lifeinscouncil.org",
    "Referer": PORTAL_URL,
}


class LifeCouncilScraper:
    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=1.0,
            status_forcelist=[429, 500, 502, 503, 504],
            raise_on_status=False,
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retries))
        self.session.headers.update(HEADERS)

    @staticmethod
    def _extract_aspnet_tokens(soup: BeautifulSoup) -> Dict[str, str]:
        tokens = {}
        for inp in soup.find_all("input", type="hidden"):
            name = inp.get("name") or inp.get("id")
            if name:
                tokens[name] = inp.get("value", "")
        return tokens

    @staticmethod
    def _clean_sfin(val: str) -> str:
        if not val:
            return ""
        # Preserve alphanumeric characters and statutory SFIN symbols (+, -, _)
        return re.sub(r"[^A-Za-z0-9+_-]", "", val.strip()).upper()

    @staticmethod
    def _clean_nav(raw_nav: Optional[str]) -> Optional[float]:
        if not raw_nav:
            return None
        cleaned = re.sub(r"[^\d.]", "", raw_nav.strip())
        if not cleaned:
            return None
        try:
            val = float(cleaned)
            return val if val > 0.0 else None
        except ValueError:
            return None

    @staticmethod
    def _parse_iso_date(raw_date: Optional[str]) -> Optional[str]:
        if not raw_date:
            return None
        raw_date = raw_date.strip()
        if not raw_date or raw_date.lower() in ("na", "n/a", "-", "--", "null"):
            return None
        try:
            return date_parser.parse(raw_date, dayfirst=True).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            return None

    def get_initial_page(self) -> Tuple[BeautifulSoup, str, Dict[str, str]]:
        resp = self.session.get(PORTAL_URL, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        form = soup.find("form")
        post_url = urljoin(PORTAL_URL, form.get("action", "")) if form else PORTAL_URL
        return soup, post_url, self._extract_aspnet_tokens(soup)

    def discover_insurers(self, soup: BeautifulSoup) -> List[Dict[str, str]]:
        select_tag = soup.find("select", id=re.compile(r"drpselectins|company", re.I)) or soup.find("select")
        if not select_tag:
            return []
        insurers = []
        for opt in select_tag.find_all("option"):
            val = opt.get("value", "").strip()
            label = opt.get_text(strip=True)
            if not val or val in ("0", "-1") or re.search(r"select|choose", label, re.I):
                continue
            insurers.append({"value": val, "name": label})
        return insurers

    def _open_calendar_and_get_days(
        self, soup: BeautifulSoup, post_url: str, ins_val: str
    ) -> Tuple[BeautifulSoup, List[Tuple[str, str]]]:
        tokens = self._extract_aspnet_tokens(soup)
        payload = {
            **tokens,
            "ctl00$txtusername": "",
            "ctl00$txtpwd": "",
            "ctl00$MainContent$drpselectinscompany": ins_val,
            "ctl00$MainContent$imgbtncalender.x": "10",
            "ctl00$MainContent$imgbtncalender.y": "10",
        }
        resp = self.session.post(post_url, data=payload, timeout=30)
        soup_cal = BeautifulSoup(resp.text, "html.parser")

        cal = soup_cal.find(lambda t: t.name == "table" and "cal" in t.get("id", "").lower())
        if not cal:
            return soup_cal, []

        day_options = []
        for a in cal.find_all("a"):
            href = a.get("href", "")
            # Filter out month navigation links ('V' prefix) and keep date postbacks
            if "CALnavdate" in href and ",'V" not in href:
                m = re.search(r"'([^']+)'\)", href)
                if m:
                    day_options.append((a.get_text(strip=True), m.group(1)))
        return soup_cal, day_options

    def _parse_table(self, soup: BeautifulSoup, insurer_name: str) -> List[Dict]:
        funds = []
        grid = soup.find(lambda t: t.name == "table" and "gridview" in t.get("id", "").lower())
        candidates = [grid] if grid else [t for t in soup.find_all("table") if len(t.find_all("tr")) > 2]

        if not candidates or not candidates[0]:
            return []

        rows = candidates[0].find_all("tr")
        if len(rows) < 2:
            return []

        headers = [c.get_text(" ", strip=True).lower() for c in rows[0].find_all(["th", "td"])]
        idx_map = {}
        for i, h in enumerate(headers):
            if "sfin" in h:
                idx_map["sfin"] = i
            elif "fund" in h or "name" in h:
                idx_map["fund_name"] = i
            elif "per unit" in h or ("nav" in h and "date" not in h):
                idx_map["latest_nav"] = i
            elif "date" in h:
                idx_map["nav_date"] = i

        # Fallbacks based on portal layout: ['Sr.no.', 'SFIN', 'Segregated Fund Name', 'NAV Date', 'NAV Per Unit']
        if "sfin" not in idx_map:
            idx_map["sfin"] = 1
        if "fund_name" not in idx_map:
            idx_map["fund_name"] = 2
        if "nav_date" not in idx_map:
            idx_map["nav_date"] = 3
        if "latest_nav" not in idx_map:
            idx_map["latest_nav"] = 4

        for row in rows[1:]:
            cells = [td.get_text(" ", strip=True) for td in row.find_all("td")]
            if not cells or len(cells) <= max(idx_map.values()):
                continue

            raw_sfin = self._clean_sfin(cells[idx_map["sfin"]])
            if not raw_sfin or len(raw_sfin) < 5 or raw_sfin == "SFIN":
                continue

            fund_name = cells[idx_map["fund_name"]].strip()
            latest_nav = self._clean_nav(cells[idx_map["latest_nav"]])
            nav_date = self._parse_iso_date(cells[idx_map["nav_date"]])

            funds.append({
                "sfin": raw_sfin,
                "fund_name": fund_name,
                "insurer_name_raw": insurer_name,
                "latest_nav": latest_nav,
                "nav_date": nav_date,
                "inception_date": None,
                "status": "ACTIVE" if latest_nav is not None else "CLOSED",
            })
        return funds

    def scrape_all_funds(self) -> Generator[Dict, None, None]:
        init_soup, post_url, _ = self.get_initial_page()
        insurers = self.discover_insurers(init_soup)
        logger.info(f"Discovered {len(insurers)} insurers dynamically from portal.")

        for ins in insurers:
            ins_name = ins["name"]
            ins_val = ins["value"]
            logger.info(f"Querying ULIP funds for: {ins_name} ({ins_val})")

            found_funds = []
            try:
                # 1. Start with fresh base tokens for each insurer
                s_base, post_url, _ = self.get_initial_page()

                # 2. Open Calendar
                s_cal, days = self._open_calendar_and_get_days(s_base, post_url, ins_val)
                if not days:
                    logger.warning(f"No calendar days visible for {ins_name}")
                    continue

                # 3. Test days in reverse chronological order (skip holidays/weekends dynamically)
                for day_txt, day_arg in reversed(days):
                    tokens_cal = self._extract_aspnet_tokens(s_cal)
                    payload_sel = {
                        **tokens_cal,
                        "__EVENTTARGET": "ctl00$MainContent$CALnavdate",
                        "__EVENTARGUMENT": day_arg,
                        "ctl00$txtusername": "",
                        "ctl00$txtpwd": "",
                        "ctl00$MainContent$drpselectinscompany": ins_val,
                    }
                    r_sel = self.session.post(post_url, data=payload_sel, timeout=30)
                    s_sel = BeautifulSoup(r_sel.text, "html.parser")

                    tokens_sel = self._extract_aspnet_tokens(s_sel)
                    txt_el = s_sel.find("input", id=lambda x: x and "txtdateselect" in x.lower())
                    txt_val = txt_el.get("value", "") if txt_el else ""

                    # 4. Click "Get Data"
                    payload_get = {
                        **tokens_sel,
                        "ctl00$txtusername": "",
                        "ctl00$txtpwd": "",
                        "ctl00$MainContent$drpselectinscompany": ins_val,
                        "ctl00$MainContent$txtdateselect": txt_val,
                        "ctl00$MainContent$btngetdetails": "Get Data",
                    }
                    r_data = self.session.post(post_url, data=payload_get, timeout=30)
                    if "not been uploaded" in r_data.text:
                        continue

                    s_data = BeautifulSoup(r_data.text, "html.parser")
                    funds = self._parse_table(s_data, ins_name)
                    if funds:
                        found_funds = funds
                        logger.info(
                            f"Successfully scraped {len(funds)} funds for {ins_name} on date '{txt_val}'."
                        )
                        break

            except Exception as e:
                logger.error(f"Error scraping {ins_name}: {e}")

            if not found_funds:
                logger.info(f"Found 0 records for '{ins_name}'.")

            for f in found_funds:
                yield f