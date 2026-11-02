"""
Module: scrapers.irdai_scraper
Purpose: Targeted diagnostic to identify the exact link patterns and containers
representing insurer entities on irdai.gov.in/life-insurers.
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
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] [DIAGNOSTIC_2] %(message)s"))
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

    # Filter out common UI navigation tokens
    ui_noise = {
        "skip to content", "main content", "english", "accessibility options",
        "zoom the page", "increase text", "decrease text", "grey scale",
        "high contrast", "low contrast", "light background", "site map",
        "home", "feedback", "contact us", "screen reader access"
    }

    meaningful_links = []
    for a in soup.find_all("a", href=True):
        text = " ".join(a.get_text().split()).strip()
        href = a["href"].strip()
        if len(text) > 4 and text.lower() not in ui_noise:
            # Check parent container classes to see how Drupal groups them
            parent_classes = a.parent.get("class", []) if a.parent else []
            grandparent_classes = a.parent.parent.get("class", []) if a.parent and a.parent.parent else []
            meaningful_links.append((text, href, parent_classes, grandparent_classes))

    logger.info("Found %d meaningful non-UI links.", len(meaningful_links))

    # Print samples covering different parts of the list
    logger.info("--- Sample First 15 Meaningful Links ---")
    for text, href, p_cls, gp_cls in meaningful_links[:15]:
        logger.info("Link: '%s' | Href: '%s' | Container: %s -> %s", text, href, p_cls, gp_cls)

    if len(meaningful_links) > 30:
        logger.info("--- Sample Middle 10 Links ---")
        for text, href, p_cls, gp_cls in meaningful_links[20:30]:
            logger.info("Link: '%s' | Href: '%s' | Container: %s -> %s", text, href, p_cls, gp_cls)

    # Return empty to allow clean pipeline run while inspecting logs
    return []