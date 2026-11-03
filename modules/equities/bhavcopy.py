"""
modules/equities/bhavcopy.py
Dynamically downloads and parses the latest available official NSE Bhavcopy CSV.
Returns a mapping of uppercase trading symbol -> closing price in INR.
"""

import csv
from datetime import datetime, timedelta
import io
import logging
from typing import Dict

from core.http_client import create_resilient_session
from core.urls import NSE_BHAVCOPY_BASE_URL, NSE_HOME_URL

logger = logging.getLogger(__name__)


def fetch_nse_bhavcopy_prices() -> Dict[str, float]:
    """
    Attempts to download closing prices for the most recent trading day
    (probing backwards up to 5 business days).
    """
    session = create_resilient_session()
    # Warm up session with NSE cookie handshake
    try:
        session.get(NSE_HOME_URL, timeout=10)
    except Exception as e:
        logger.debug("NSE session warmup notice: %s", e)

    today = datetime.now()
    price_map: Dict[str, float] = {}

    for i in range(1, 6):
        trade_date = today - timedelta(days=i)
        if trade_date.weekday() >= 5:  # Skip Saturday/Sunday
            continue

        date_str = trade_date.strftime("%d%m%Y")
        url = NSE_BHAVCOPY_BASE_URL.format(date=date_str)

        try:
            resp = session.get(url, timeout=15)
            if resp.status_code == 200 and "SYMBOL" in resp.text:
                reader = csv.DictReader(io.StringIO(resp.text))
                for raw_row in reader:
                    # Clean all header keys by stripping whitespace
                    row = {k.strip(): v.strip() for k, v in raw_row.items() if k and v}
                    sym = row.get("SYMBOL", "").upper()
                    close_raw = row.get("CLOSE_PRICE") or row.get("LAST_PRICE") or "0"
                    try:
                        price = float(close_raw.replace(",", ""))
                        if price > 0:
                            price_map[sym] = round(price, 2)
                    except ValueError:
                        continue

                logger.info("Retrieved %d closing prices from NSE Bhavcopy (%s).", len(price_map), date_str)
                return price_map
        except Exception as e:
            logger.debug("NSE Bhavcopy query for %s returned: %s", date_str, e)

    return price_map

