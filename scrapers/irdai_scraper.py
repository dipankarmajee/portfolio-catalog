"""
Module: scrapers.irdai_scraper
Purpose: Targeted diagnostic to isolate Liferay content portlets and entity records.
"""

import logging
import sys
import re
import requests
from bs4 import BeautifulSoup
from urllib3.util import create_urllib3_context
from requests.adapters import HTTPAdapter

logger = logging.getLogger("scrapers.irdai")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] [DIAGNOSTIC_3] %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

TARGET_URL = "https://irdai.gov.in/life-insurers"

class SSLHonorAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.load_default_certs()
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)

def scrape_registered_life_insurers():
    session = requests.Session()
    session.mount("https://", SSLHonorAdapter())
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    })

    resp = session.get(TARGET_URL, timeout=30)
    soup = BeautifulSoup(resp.text, "html.parser")

    # 1. Identify all Liferay Portlet containers
    portlets = soup.find_all(["section", "div"], class_=re.compile(r"portlet"))
    logger.info("Found %d portlet container(s) on page.", len(portlets))
    for p in portlets:
        p_id = p.get("id", "")
        p_class = p.get("class", [])
        p_text_sample = " ".join(p.get_text().split())[:80]
        logger.info("Portlet id='%s' class='%s' | Text preview: '%s'", p_id, p_class, p_text_sample)

    # 2. Filter out navigation bars and locate non-nav text blocks
    # Remove navbars, headers, and footers from search
    for nav in soup.find_all(["nav", "header", "footer"]):
        nav.decompose()
    for nav_div in soup.find_all("div", class_=re.compile(r"navbar|menu|dropdown")):
        nav_div.decompose()

    # Inspect remaining non-nav content links
    remaining_links = []
    for a in soup.find_all("a", href=True):
        text = " ".join(a.get_text().split()).strip()
        href = a["href"].strip()
        if len(text) > 3 and not href.startswith("javascript:"):
            remaining_links.append((text, href))

    logger.info("Found %d non-nav links in main body.", len(remaining_links))
    for text, href in remaining_links[:25]:
        logger.info("Content Link: '%s' -> %s", text, href)

    # 3. Check if there are raw paragraphs or div cards mentioning known insurer names
    body_text = soup.get_text()
    for sample_keyword in ["HDFC", "Life Insurance Corporation", "SBI Life", "ICICI Prudential", "Max Life", "Bajaj"]:
        present = sample_keyword.lower() in body_text.lower()
        logger.info("Keyword check '%s' present in body: %s", sample_keyword, present)

    return []