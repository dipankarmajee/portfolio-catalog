"""
Module: scrapers.irdai_scraper
Purpose: Diagnostic inspector to dump actual DOM elements on IRDAI endpoint.
"""

import logging
import sys
import requests
from bs4 import BeautifulSoup
from urllib3.util import create_urllib3_context
from requests.adapters import HTTPAdapter

logger = logging.getLogger("scrapers.irdai")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] [DIAGNOSTIC] %(message)s"))
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
    logger.info("HTTP Status: %d | Content Length: %d bytes", resp.status_code, len(resp.content))

    soup = BeautifulSoup(resp.text, "html.parser")

    # 1. Print all tables and their header rows if any exist
    tables = soup.find_all("table")
    logger.info("Found %d table(s) on page.", len(tables))
    for idx, tbl in enumerate(tables):
        headers = [th.get_text(strip=True) for th in tbl.find_all(["th", "td"])]
        logger.info("Table %d first row elements: %s", idx, headers[:6])

    # 2. Inspect Drupal main content view container
    content = soup.find("main") or soup.find("div", class_="region-content") or soup.find("body")
    if content:
        # Find any links with 'insurer' or company-like patterns
        links = content.find_all("a")
        logger.info("Found %d links inside main region.", len(links))
        sample_links = [a.get_text(strip=True) for a in links if len(a.get_text(strip=True)) > 5]
        logger.info("Sample links (first 10): %s", sample_links[:10])

    # Exit gracefully without throwing an exception to inspect the log
    return []