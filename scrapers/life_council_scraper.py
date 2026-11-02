"""
Module: scrapers.life_council_scraper
Purpose: 100% Dynamic discovery and extraction of ULIP SFIN fund NAVs
from the Life Insurance Council central portal without hardcoded form parameters.
"""

import logging
import sys
import re
from datetime import datetime
from typing import List, Dict, Optional
import requests
from bs4 import BeautifulSoup
from urllib3.util import create_urllib3_context
from requests.adapters import HTTPAdapter

logger = logging.getLogger("scrapers.life_council")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] [COUNCIL_ULIP] %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

COUNCIL_NAV_URL = "https://www.lifeinscouncil.org/industry-info/nav"
REQUEST_TIMEOUT = 30

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.lifeinscouncil.org",
    "Referer": COUNCIL_NAV_URL
}

class SSLHonorAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.load_default_certs()
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)

def get_council_session() -> requests.Session:
    session = requests.Session()
    session.mount("https://", SSLHonorAdapter())
    session.headers.update(HEADERS)
    return session

def clean_text(raw_text: str) -> str:
    return " ".join(raw_text.split()).strip()

def parse_ulip_table(soup: BeautifulSoup, insurer_reg: str, default_date: str) -> List[Dict]:
    """
    Dynamically identifies table rows containing valid SFIN identifiers.
    SFIN format: ULIF followed by alphanumeric segments or standard 16-char statutory codes.
    """
    funds = []
    tables = soup.find_all("table")

    sfin_pattern = re.compile(r"\b(ULI[FP][A-Z0-9\/\-]{8,20}|[A-Z]{3,4}\d{2,6}[A-Z0-9\/\-]{6,16})\b", re.IGNORECASE)

    for table in tables:
        for tr in table.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if len(cells) < 3:
                continue

            row_texts = [clean_text(c.get_text()) for c in cells]
            
            sfin_candidate = None
            nav_candidate = None
            date_candidate = default_date
            name_candidate = None

            # 1. Search for SFIN
            for txt in row_texts:
                match = sfin_pattern.search(txt)
                if match:
                    sfin_candidate = match.group(1).upper()
                    break

            if not sfin_candidate:
                continue

            # 2. Search for NAV (float number > 0)
            for txt in reversed(row_texts):
                cleaned_num = re.sub(r"[^\d\.]", "", txt)
                if cleaned_num and "." in cleaned_num:
                    try:
                        val = float(cleaned_num)
                        if 1.0 <= val <= 50000.0:
                            nav_candidate = val
                            break
                    except ValueError:
                        pass

            # 3. Search for Fund Name
            for txt in row_texts:
                if txt != sfin_candidate and len(txt) > 5 and not re.match(r"^[\d\.\-\/\s]+$", txt):
                    if not any(header_word in txt.lower() for header_word in ["sfin", "nav", "fund name", "date"]):
                        name_candidate = txt
                        break

            # 4. Search for Valuation Date
            for txt in row_texts:
                date_match = re.search(r"\b(\d{2}[-\/]\d{2}[-\/]\d{4}|\d{4}[-\/]\d{2}[-\/]\d{2})\b", txt)
                if date_match:
                    raw_d = date_match.group(1).replace("/", "-")
                    if len(raw_d.split("-")[0]) == 2:
                        d_parts = raw_d.split("-")
                        date_candidate = f"{d_parts[2]}-{d_parts[1]}-{d_parts[0]}"
                    else:
                        date_candidate = raw_d
                    break

            if sfin_candidate and nav_candidate:
                clean_fund_name = name_candidate if name_candidate else f"ULIP Fund {sfin_candidate}"
                funds.append({
                    "sfin": sfin_candidate,
                    "fund_name": clean_fund_name,
                    "insurer_id": f"INS_{insurer_reg}",
                    "reg_number": insurer_reg,
                    "latest_nav": nav_candidate,
                    "nav_date": date_candidate,
                    "status": "ACTIVE"
                })

    return funds

def scrape_council_ulips_for_insurer(session: requests.Session, reg_number: str, insurer_name: str) -> List[Dict]:
    """Dynamically queries the Council portal for a specific insurer."""
    try:
        # Step 1: Initial handshake to capture dynamic form tokens
        resp = session.get(COUNCIL_NAV_URL, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        form = soup.find("form")
        if not form:
            return []

        action_url = form.get("action") or COUNCIL_NAV_URL
        if not action_url.startswith("http"):
            action_url = requests.compat.urljoin(COUNCIL_NAV_URL, action_url)

        # Step 2: Dynamically aggregate all hidden form fields (tokens, viewstates)
        payload = {}
        for inp in form.find_all("input", {"type": "hidden"}):
            name = inp.get("name")
            val = inp.get("value", "")
            if name:
                payload[name] = val

        # Step 3: Match the insurer selection dropdown dynamically
        selects = form.find_all("select")
        insurer_select_name = None
        target_option_val = None

        for sel in selects:
            options = sel.find_all("option")
            for opt in options:
                opt_text = opt.get_text().lower()
                # Match by registration number or company name tokens
                if reg_number in opt_text or any(token in opt_text for token in insurer_name.lower().split() if len(token) > 4):
                    insurer_select_name = sel.get("name")
                    target_option_val = opt.get("value")
                    break
            if insurer_select_name:
                break

        if insurer_select_name and target_option_val:
            payload[insurer_select_name] = target_option_val

        today_str = datetime.utcnow().strftime("%Y-%m-%d")

        # Step 4: Submit search request
        post_resp = session.post(action_url, data=payload, timeout=REQUEST_TIMEOUT)
        if post_resp.status_code == 200:
            result_soup = BeautifulSoup(post_resp.text, "html.parser")
            return parse_ulip_table(result_soup, reg_number, today_str)

    except Exception as exc:
        logger.warning("Could not dynamically query Council for %s (Reg: %s): %s", insurer_name, reg_number, exc)

    return []

def scrape_all_ulip_funds(active_insurers: List[Dict]) -> List[Dict]:
    """
    Iterates dynamically across all registered Life Insurers discovered
    in master_insurers and retrieves their active SFIN funds.
    """
    logger.info("Initiating dynamic ULIP SFIN extraction across %d life insurers...", len(active_insurers))
    session = get_council_session()
    all_funds: Dict[str, Dict] = {}

    for insurer in active_insurers:
        reg_no = str(insurer.get("reg_number", "")).strip()
        name = insurer.get("insurer_name") or insurer.get("entity_name") or ""

        funds = scrape_council_ulips_for_insurer(session, reg_no, name)
        logger.info("Insurer %s (Reg %s): Extracted %d ULIP SFIN funds.", name, reg_no, len(funds))

        for f in funds:
            all_funds[f["sfin"]] = f

    logger.info("Total unique ULIP SFIN funds extracted dynamically: %d", len(all_funds))
    return list(all_funds.values())