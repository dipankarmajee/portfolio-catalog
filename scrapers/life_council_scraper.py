"""
Module: scrapers.life_council_scraper
Purpose: 100% Dynamic crawler for Life Insurance Council ASP.NET NAV portal.
Maintains full ASP.NET ViewState lifecycle and extracts SFIN fund NAV records.
"""

import logging
import sys
import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from urllib.parse import urljoin, quote, urlparse
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
REQUEST_TIMEOUT = 30

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
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

def normalize_url(raw_url: str) -> str:
    """Properly encodes spaces and special characters in ASP.NET paths."""
    parts = urlparse(raw_url)
    encoded_path = quote(parts.path)
    return f"{parts.scheme}://{parts.netloc}{encoded_path}"

def discover_nav_portal_url(session: requests.Session) -> Optional[str]:
    """Dynamically locates the NAV portal link from navigation."""
    logger.info("Discovering live NAV portal URL dynamically from %s...", BASE_COUNCIL_URL)
    try:
        resp = session.get(BASE_COUNCIL_URL, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            return None

        soup = BeautifulSoup(resp.text, "html.parser")
        candidates = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            text = clean_text(a.get_text()).lower()
            lower_href = href.lower()

            if any(k in text for k in ["nav", "ulip", "sfin", "fund"]) or any(k in lower_href for k in ["nav", "fund_nav"]):
                if not href.startswith("javascript:") and not href.startswith("#"):
                    full_link = urljoin(BASE_COUNCIL_URL, href)
                    candidates.append(full_link)

        if candidates:
            # Prefer direct fund NAV pages
            for c in candidates:
                if "fund_nav" in c.lower() or "list_of_fund" in c.lower():
                    return normalize_url(c)
            return normalize_url(candidates[0])

    except Exception as exc:
        logger.warning("Dynamic menu discovery exception: %s", exc)

    return None

def extract_aspnet_state(soup: BeautifulSoup) -> Dict[str, str]:
    """Extracts all required ASP.NET hidden state inputs."""
    state = {}
    for inp in soup.find_all("input", {"type": "hidden"}):
        name = inp.get("name")
        val = inp.get("value", "")
        if name:
            state[name] = val
    return state

def parse_ulip_table(soup: BeautifulSoup, default_reg: str = "UNKNOWN") -> List[Dict]:
    """
    Scans all HTML tables for IRDAI SFIN patterns, fund descriptions, and NAV values.
    """
    funds = []
    tables = soup.find_all("table")
    sfin_pattern = re.compile(r"\b(ULI[FP][A-Z0-9\/\-]{8,25}|[A-Z]{3,4}\d{2,6}[A-Z0-9\/\-]{6,16})\b", re.IGNORECASE)

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

            # 2. Search for NAV
            nav_candidate = None
            for txt in reversed(row_texts):
                cleaned_num = re.sub(r"[^\d\.]", "", txt)
                if cleaned_num and "." in cleaned_num:
                    try:
                        val = float(cleaned_num)
                        if 1.0 <= val <= 100000.0:
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
            date_candidate = datetime.utcnow().strftime("%Y-%m-%d")
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

            # Extract insurer statutory code directly from last 3 digits of SFIN if present
            sfin_clean = sfin_candidate.strip()
            inferred_reg = default_reg
            if len(sfin_clean) >= 16:
                tail_code = sfin_clean[-3:]
                if tail_code.isdigit():
                    inferred_reg = str(int(tail_code))

            if sfin_candidate and nav_candidate:
                funds.append({
                    "sfin": sfin_candidate,
                    "fund_name": name_candidate if name_candidate else f"ULIP Fund {sfin_candidate}",
                    "insurer_id": f"INS_{inferred_reg}",
                    "reg_number": inferred_reg,
                    "latest_nav": nav_candidate,
                    "nav_date": date_candidate,
                    "status": "ACTIVE"
                })

    return funds

def scrape_all_ulip_funds(active_insurers: List[Dict]) -> List[Dict]:
    """
    Executes dynamic traversal of the ASP.NET portal and harvests ULIP funds.
    """
    session = get_session()
    nav_url = discover_nav_portal_url(session)

    if not nav_url:
        logger.warning("Could not dynamically resolve active NAV portal from %s.", BASE_COUNCIL_URL)
        return []

    logger.info("Connecting to NAV portal at: %s", nav_url)
    session.headers.update({"Referer": nav_url})

    try:
        get_resp = session.get(nav_url, timeout=REQUEST_TIMEOUT)
        if get_resp.status_code != 200:
            logger.warning("Portal landing returned HTTP %d", get_resp.status_code)
            return []
    except Exception as exc:
        logger.warning("Failed connecting to NAV portal: %s", exc)
        return []

    initial_soup = BeautifulSoup(get_resp.text, "html.parser")

    # Attempt 1: Check if landing page contains pre-loaded data
    landing_funds = parse_ulip_table(initial_soup)
    if landing_funds:
        logger.info("Found %d ULIP funds directly on initial landing view.", len(landing_funds))
        return landing_funds

    form = initial_soup.find("form")
    if not form:
        logger.warning("No ASP.NET form tag found on %s", nav_url)
        return []

    action_url = form.get("action") or nav_url
    if not action_url.startswith("http"):
        action_url = urljoin(nav_url, action_url)
    action_url = normalize_url(action_url)

    state = extract_aspnet_state(initial_soup)
    logger.info("Captured %d ASP.NET state variables (__VIEWSTATE length: %d)", len(state), len(state.get("__VIEWSTATE", "")))

    all_funds: Dict[str, Dict] = {}

    # Attempt 2: Try bulk query without filtering by individual insurer
    # Often clicking the primary submit button returns all entities
    submit_buttons = form.find_all("input", {"type": "submit"})
    if submit_buttons:
        btn_name = submit_buttons[0].get("name")
        btn_val = submit_buttons[0].get("value", "Submit")
        bulk_payload = state.copy()
        if btn_name:
            bulk_payload[btn_name] = btn_val

        try:
            bulk_resp = session.post(action_url, data=bulk_payload, timeout=REQUEST_TIMEOUT)
            if bulk_resp.status_code == 200:
                bulk_soup = BeautifulSoup(bulk_resp.text, "html.parser")
                bulk_funds = parse_ulip_table(bulk_soup)
                if bulk_funds:
                    logger.info("Bulk query extracted %d total ULIP funds across all insurers.", len(bulk_funds))
                    for f in bulk_funds:
                        all_funds[f["sfin"]] = f
                    return list(all_funds.values())
        except Exception as exc:
            logger.warning("Bulk query failed: %s", exc)

    # Attempt 3: Query per insurer via dropdown selection
    selects = form.find_all("select")
    insurer_select = None
    for sel in selects:
        opts_text = " ".join([o.get_text().lower() for o in sel.find_all("option")])
        if any(term in opts_text for term in ["life", "hdfc", "sbi", "prudential", "lic"]):
            insurer_select = sel
            break

    if not insurer_select:
        logger.warning("Could not identify insurer dropdown control.")
        return list(all_funds.values())

    sel_name = insurer_select.get("name")
    options = insurer_select.find_all("option")
    logger.info("Found insurer select '%s' with %d options.", sel_name, len(options))

    for opt in options:
        opt_val = opt.get("value", "").strip()
        opt_label = clean_text(opt.get_text())
        if not opt_val or opt_val in ["0", "-1", "Select", "All"]:
            continue

        # Match option to known insurer
        matched_insurer = None
        for ins in active_insurers:
            ins_name = (ins.get("insurer_name") or ins.get("entity_name") or "").lower()
            reg_num = str(ins.get("reg_number", "")).strip()
            if reg_num and reg_num in opt_label:
                matched_insurer = ins
                break
            tokens = [t for t in ins_name.split() if len(t) > 4 and t not in ["insurance", "company", "limited"]]
            if tokens and all(t in opt_label.lower() for t in tokens[:2]):
                matched_insurer = ins
                break

        assigned_reg = str(matched_insurer.get("reg_number", "UNKNOWN")) if matched_insurer else "UNKNOWN"

        post_payload = state.copy()
        post_payload[sel_name] = opt_val
        post_payload["__EVENTTARGET"] = sel_name
        post_payload["__EVENTARGUMENT"] = ""

        # Include button click simulation if required
        if submit_buttons and submit_buttons[0].get("name"):
            post_payload[submit_buttons[0]["name"]] = submit_buttons[0].get("value", "Submit")

        try:
            resp = session.post(action_url, data=post_payload, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                result_soup = BeautifulSoup(resp.text, "html.parser")
                # Update ViewState for subsequent requests
                new_state = extract_aspnet_state(result_soup)
                if new_state.get("__VIEWSTATE"):
                    state = new_state

                funds = parse_ulip_table(result_soup, default_reg=assigned_reg)
                for f in funds:
                    all_funds[f["sfin"]] = f
                if funds:
                    logger.info("Option '%s' (Reg %s): Extracted %d ULIP SFIN funds.", opt_label, assigned_reg, len(funds))
        except Exception as exc:
            logger.warning("Error querying option '%s': %s", opt_label, exc)

    logger.info("Total dynamic ULIP funds gathered: %d", len(all_funds))
    return list(all_funds.values())