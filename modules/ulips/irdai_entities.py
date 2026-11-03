"""
modules/ulips/irdai_entities.py
Directly fetches and parses the official IRDAI statutory Life Insurers directory.
Restricted exclusively to registered life insurance companies.
URL: https://irdai.gov.in/list-of-life-insurers1
Strictly dynamic: zero hardcoded insurer lists or static fallback arrays.
"""

import logging
import re
from typing import Dict, Generator, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core.constants import URL_EXTRACT_PATTERN
from core.enums import InsurerCategory
from core.http_client import create_resilient_session
from core.text_utils import clean_english_text
from core.urls import IRDAI_LIFE_INSURERS_URL

logger = logging.getLogger(__name__)


class IRDAIEntityScraper:
    def __init__(self):
        self.session = create_resilient_session()

    def scrape_life_insurers(self) -> Generator[Dict, None, None]:
        """
        Dynamically extracts all registered life insurance companies directly from the official IRDAI portal.
        """
        logger.info("Fetching official life insurers registry from %s...", IRDAI_LIFE_INSURERS_URL)
        resp = self.session.get(IRDAI_LIFE_INSURERS_URL, timeout=25)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table")
        if not table:
            logger.warning("No table found on IRDAI life insurers page.")
            return

        rows = table.find_all("tr")
        count = 0

        for tr in rows:
            cells = [clean_english_text(td.get_text()) for td in tr.find_all(["td", "th"])]
            if len(cells) < 3:
                continue

            # First row is header
            sl_no, name, reg_no = cells[0], cells[1], cells[2]
            if not sl_no.isdigit() or not reg_no.isdigit():
                continue

            website_url = None
            link = tr.find("a", href=True)
            if link and ("http" in link["href"] or "www" in link["href"]):
                website_url = link["href"].strip()
            else:
                for td in tr.find_all("td"):
                    td_text = td.get_text().strip()
                    m = URL_EXTRACT_PATTERN.search(td_text)
                    if m:
                        url = m.group(0).rstrip("./")
                        if url.lower().startswith("www."):
                            url = "https://" + url
                        website_url = url
                        break

            count += 1
            yield {
                "entity_name": name,
                "insurer_name": name,
                "reg_number": reg_no,
                "category": InsurerCategory.LIFE_INSURERS.value,
                "website": website_url,
                "source_url": IRDAI_LIFE_INSURERS_URL,
            }

        logger.info("Dynamically parsed %d authorized life insurers from IRDAI.", count)
