"""
Module: scrapers.life_council_scraper
Purpose: 100% Dynamic discovery of the Life Insurance Council NAV endpoint
and extraction of active ULIP SFIN fund data without hardcoded routes.
"""

import logging
import sys
import re
from datetime import datetime
from typing import List, Dict, Optional, Set
from urllib.parse import urljoin
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

BASE_COUNCIL_URL = "https://www.lifeinscouncil.org"
REQUEST_TIMEOUT = 25

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

def get_session() -> requests.Session:
    session = requests.Session()
    session.mount("https://", SSLHonorAdapter())
    session.headers.update(HEADERS)
    return session

def clean_text(raw_text: str) -> str:
    return " ".join(raw_text.split()).strip()

def discover_nav_portal_url(session: requests.Session) -> Optional[str]:
    """
    Dynamically crawls the Life Insurance Council homepage and menus
    to discover the actual live NAV endpoint URL.
    """
    logger.info("Discovering live NAV portal URL dynamically from %s...", BASE_COUNCIL_URL)
    try:
        resp = session.get(BASE_COUNCIL_URL, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            logger.warning("Council root returned HTTP %d", resp.status_code)
            return None

        soup = BeautifulSoup(resp.text, "html.parser")
        
        # Look for NAV or ULIP related links in navigation / anchors
        candidates: List[str] = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            text = clean_text(a.get_text()).lower()
            lower_href = href.lower()

            if any(term in text for term in ["nav", "ulip", "sfin", "fund performance"]) or \
               any(term in lower_href for term in ["nav", "ulip", "sfin"]):
                if not href.startswith("javascript:") and not href.startswith("#"):
                    full_link = urljoin(BASE_COUNCIL_URL, href)
                    candidates.append(full_link)

        if candidates:
            # Prefer links with 'nav' in the path or anchor
            best_link = candidates[0]
            for c in candidates:
                if "/nav" in c.lower() or "nav" in c.lower():
                    best_link = c
                    break
            logger.info("Dynamically located NAV portal link: %s", best_link)
            return best_link

    except Exception as exc:
        logger.warning("Dynamic discovery encountered an issue: %s", exc)

    return None

def parse_ulip_table(soup: BeautifulSoup, insurer_reg: str, default_date: str) -> List[Dict]:
    """
    Dynamically extracts ULIP funds by identifying IRDAI SFIN patterns,
    fund descriptions, and float NAV figures across all tables.
    """
    funds = []
    tables = soup.find_all("table")
    sfin_pattern = re.compile(r"\b(ULI[FP][A-Z0-9\/\-]{8,20}|[A-Z]{3,4}\d{2,6}[A-Z0-9\/\-]{6,16})\b", re.IGNORECASE)

    for table in tables:
        for tr in table.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if len(cells) < 2:
                continue

            row_texts = [clean_text(c.get_text()) for c in cells]

            # 1. Search for SFIN
            sfin_candidate = None
            for txt in row_texts:
                match = sfin_pattern.search(txt)
                if match:
                    sfin_candidate = match.group(1).upper()
                    break

            if not sfin_candidate:
                continue

            # 2. Search for NAV (float between 1.0 and 50000.0)
            nav_candidate = None
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
            name_candidate = None
            for txt in row_texts:
                if txt != sfin_candidate and len(txt) > 5 and not re.match(r"^[\d\.\-\/\s]+$", txt):
                    if not any(header_word in txt.lower() for header_word in ["sfin", "nav", "fund name", "date"]):
                        name_candidate = txt
                        break

            # 4. Search for Valuation Date
            date_candidate = default_date
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
                funds.append({
                    "sfin": sfin_candidate,
                    "fund_name": name_candidate if name_candidate else f"ULIP Fund {sfin_candidate}",
                    "insurer_id": f"INS_{insurer_reg}",
                    "reg_number": insurer_reg,
                    "latest_nav": nav_candidate,
                    "nav_date": date_candidate,
                    "status": "ACTIVE"
                })

    return funds

def scrape_all_ulip_funds(active_insurers: List[Dict]) -> List[Dict]:
    """
    Dynamically finds the live NAV portal, submits requests for each active life insurer,
    and returns parsed ULIP SFIN fund records.
    """
    session = get_session()
    nav_url = discover_nav_portal_url(session)

    if not nav_url:
        logger.warning("Could not dynamically resolve active NAV portal from %s. Skipping ULIP sync.", BASE_COUNCIL_URL)
        return []

    logger.info("Opening NAV portal page at: %s", nav_url)
    try:
        resp = session.get(nav_url, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            logger.warning("NAV portal returned HTTP %d", resp.status_code)
            return []
    except Exception as exc:
        logger.warning("Failed connecting to NAV portal: %s", exc)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    today_str = datetime.utcnow().strftime("%Y-%m-%d")

    # Step 1: Check if the discovered page already directly contains table data
    direct_funds = parse_ulip_table(soup, "ALL", today_str)
    if direct_funds:
        logger.info("Extracted %d ULIP funds directly from landing table.", len(direct_funds))
        return direct_funds

    # Step 2: Dynamically inspect form for insurer inputs
    form = soup.find("form")
    if not form:
        logger.info("No query form located on %s.", nav_url)
        return []

    action_url = form.get("action") or nav_url
    if not action_url.startswith("http"):
        action_url = urljoin(nav_url, action_url)

    # Harvest all hidden inputs dynamically (ViewState, CSRF tokens, etc.)
    base_payload = {}
    for inp in form.find_all("input", {"type": "hidden"}):
        name = inp.get("name")
        val = inp.get("value", "")
        if name:
            base_payload[name] = val

    selects = form.find_all("select")
    all_funds: Dict[str, Dict] = {}

    for insurer in active_insurers:
        reg_no = str(insurer.get("reg_number", "")).strip()
        name = insurer.get("insurer_name") or insurer.get("entity_name") or ""
        payload = base_payload.copy()

        # Find matching dropdown and option dynamically
        for sel in selects:
            sel_name = sel.get("name")
            for opt in sel.find_all("option"):
                opt_txt = opt.get_text().lower()
                if reg_no in opt_txt or any(tok in opt_txt for tok in name.lower().split() if len(tok) > 4):
                    if sel_name and opt.get("value"):
                        payload[sel_name] = opt.get("value")
                    break

        try:
            post_resp = session.post(action_url, data=payload, timeout=REQUEST_TIMEOUT)
            if post_resp.status_code == 200:
                result_soup = BeautifulSoup(post_resp.text, "html.parser")
                extracted = parse_ulip_table(result_soup, reg_no, today_str)
                for f in extracted:
                    all_funds[f["sfin"]] = f
                if extracted:
                    logger.info("Insurer %s (Reg %s): Extracted %d ULIP funds.", name, reg_no, len(extracted))
        except Exception as exc:
            logger.warning("Error fetching ULIPs for %s: %s", name, exc)

    logger.info("Total dynamic ULIP funds gathered: %d", len(all_funds))
    return list(all_funds.values())