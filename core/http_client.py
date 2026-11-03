"""
core/http_client.py
Resilient HTTP client with retry backoff, browser header spoofing, and rate limiting.
"""

import logging
from typing import Dict, Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from core.config import BACKOFF_FACTOR, DEFAULT_HEADERS, DEFAULT_TIMEOUT, MAX_RETRIES, SEC_HEADERS
from core.exceptions import FetchError

logger = logging.getLogger(__name__)


def create_resilient_session(
    headers: Optional[Dict[str, str]] = None,
    total_retries: int = MAX_RETRIES,
    backoff: float = BACKOFF_FACTOR,
) -> requests.Session:
    """
    Creates and configures a requests.Session with connection pooling and automated retries.
    """
    session = requests.Session()
    retries = Retry(
        total=total_retries,
        backoff_factor=backoff,
        status_forcelist=[429, 500, 502, 503, 504],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retries, pool_connections=10, pool_maxsize=20)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    req_headers = dict(DEFAULT_HEADERS)
    if headers:
        req_headers.update(headers)
    session.headers.update(req_headers)
    return session


class HttpClient:
    """Convenience wrapper for making HTTP calls with built-in resilience and error handling."""

    def __init__(self, headers: Optional[Dict[str, str]] = None):
        self.session = create_resilient_session(headers)

    def get(self, url: str, timeout: int = DEFAULT_TIMEOUT, **kwargs) -> requests.Response:
        try:
            resp = self.session.get(url, timeout=timeout, **kwargs)
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            logger.error("HTTP GET failed for %s: %s", url, e)
            raise FetchError(f"Failed to fetch {url}: {e}") from e

    def post(self, url: str, timeout: int = DEFAULT_TIMEOUT, **kwargs) -> requests.Response:
        try:
            resp = self.session.post(url, timeout=timeout, **kwargs)
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            logger.error("HTTP POST failed for %s: %s", url, e)
            raise FetchError(f"Failed to post to {url}: {e}") from e


def get_sec_session() -> requests.Session:
    """Creates a session adhering to the US SEC EDGAR Fair Access Policy."""
    return create_resilient_session(headers=SEC_HEADERS)

