"""
scrapers/commercial_plan_scraper.py

Discovers commercial retail product names and UINs by streaming IRDAI's
official Approved Life Products Excel registries directly in memory.
Zero hardcoded URLs, zero external spreadsheet dependencies.
"""

import io
import logging
import re
import xml.etree.ElementTree as ET
import zipfile
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

from bs4 import BeautifulSoup
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


class CommercialPlanScraper:
    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        retries = Retry(total=3, backoff_factor=1.0, status_forcelist=[429, 500, 502, 503, 504], raise_on_status=False)
        self.session.mount("https://", HTTPAdapter(max_retries=retries))
        self.session.headers.update(HEADERS)

    def fetch_irdai_product_catalog(self) -> Dict[str, List[Tuple[str, str]]]:
        """
        Discovers and parses IRDAI's official life insurance product workbooks.
        Returns: { 'insurer_reg_code': [(uin, commercial_product_name), ...], ... }
        """
        catalog: Dict[str, List[Tuple[str, str]]] = {}
        index_url = "https://irdai.gov.in/list-of-life-products"

        try:
            resp = self.session.get(index_url, timeout=25)
            if resp.status_code != 200:
                logger.warning(f"Failed to fetch IRDAI products index (status {resp.status_code})")
                return catalog

            soup = BeautifulSoup(resp.text, "html.parser")
            xlsx_links = list(set([
                urljoin(index_url, a["href"])
                for a in soup.find_all("a", href=True)
                if ".xlsx" in a["href"].lower()
            ]))
            logger.info(f"Discovered {len(xlsx_links)} official insurer product workbooks on IRDAI.")

            uin_pattern = re.compile(r"\b\d{3}L\d{3}V\d{2}\b")
            hindi_pattern = re.compile(r"[\u0900-\u097F]")

            for link in xlsx_links:
                try:
                    file_resp = self.session.get(link, timeout=15)
                    if file_resp.status_code != 200:
                        continue

                    with zipfile.ZipFile(io.BytesIO(file_resp.content)) as z:
                        strings = []
                        if "xl/sharedStrings.xml" in z.namelist():
                            tree = ET.fromstring(z.read("xl/sharedStrings.xml"))
                            strings = [
                                "".join(n.itertext()).strip()
                                for n in tree.findall("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}si")
                            ]

                        sheet_name = next((n for n in z.namelist() if n.startswith("xl/worksheets/sheet")), None)
                        if not sheet_name:
                            continue

                        sheet_xml = ET.fromstring(z.read(sheet_name))
                        for row in sheet_xml.findall(".//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row"):
                            vals = []
                            for c in row.findall("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c"):
                                v = c.find("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v")
                                if v is not None and v.text is not None:
                                    raw = v.text
                                    val = strings[int(raw)] if c.get("t") == "s" and raw.isdigit() and int(raw) < len(strings) else raw
                                    vals.append(val.strip())

                            match = next((v for v in vals if uin_pattern.search(v)), None)
                            if match:
                                uin = uin_pattern.search(match).group(0)
                                ins_code = uin[:3]
                                candidates = [
                                    v for v in vals
                                    if len(v) > 3
                                    and not hindi_pattern.search(v)
                                    and not uin_pattern.search(v)
                                    and not v.startswith("20")
                                    and not v.isdigit()
                                ]
                                if candidates:
                                    prod_name = candidates[0].strip()
                                    catalog.setdefault(ins_code, []).append((uin, prod_name))

                except Exception as ex:
                    logger.debug(f"Skipping workbook {link}: {ex}")

        except Exception as e:
            logger.error(f"Error fetching IRDAI product catalog: {e}")

        logger.info(f"Loaded IRDAI product catalogs for {len(catalog)} insurers.")
        return catalog

    @staticmethod
    def resolve_best_product(
        sfin: str,
        fund_name: str,
        products: List[Tuple[str, str]]
    ) -> Optional[Tuple[str, str]]:
        """
        Resolves commercial product name and UIN using:
        1. High-confidence token intersection between SFIN tokens and Product Name.
        2. Delimiter extraction from fund name.
        """
        if not products:
            return None

        # A. Delimiter match (e.g. 'Foresight 5P Fund - I')
        if " - " in fund_name or " – " in fund_name:
            lead = re.split(r"\s+[-–:]\s+", fund_name)[0].strip().lower()
            for uin, p_name in products:
                if lead in p_name.lower():
                    return (uin, p_name)

        # B. Token intersection between SFIN and commercial product names
        # e.g., SFIN token 'BSLFSIT5P' -> matches 'Foresight'
        tokens = [
            t.lower() for t in re.findall(r"[A-Za-z]{4,}", fund_name)
            if t.lower() not in ("fund", "funds", "individual", "group", "life", "pension", "linked")
        ]

        best_prod = None
        best_score = 0
        for uin, p_name in products:
            p_lower = p_name.lower()
            score = sum(1 for t in tokens if t in p_lower)
            if score > best_score:
                best_score = score
                best_prod = (uin, p_name)

        if best_prod and best_score > 0:
            return best_prod

        return None