"""
core/text_utils.py
Text sanitization and English normalization utilities.
"""

import re
import unicodedata
from typing import Optional

from core.constants import (
    DEVANAGARI_PATTERN,
    STOPWORDS_CORPORATE,
    WHITESPACE_PATTERN,
)


def clean_english_text(text: Optional[str]) -> str:
    """
    Normalizes text to clean English:
    1. Normalizes unicode (NFKD)
    2. Strips Devanagari/Hindi characters
    3. Strips leading slash/punctuation artifacts
    4. Normalizes whitespace
    """
    if not text:
        return ""
    # Normalize unicode
    normalized = unicodedata.normalize("NFKD", str(text))
    # Remove Devanagari script
    stripped = DEVANAGARI_PATTERN.sub(" ", normalized)
    # Remove leading slash or stray bullet symbols
    cleaned = re.sub(r"^[/\-•*|~>\s]+", "", stripped)
    # Collapse multiple whitespaces
    return WHITESPACE_PATTERN.sub(" ", cleaned).strip()


def has_devanagari(text: Optional[str]) -> bool:
    """Checks whether text contains Devanagari/Hindi script."""
    if not text:
        return False
    return bool(DEVANAGARI_PATTERN.search(str(text)))


def canonicalize_identifier(prefix: str, identifier: str) -> str:
    """
    Constructs a consistent primary key UID.
    Example: canonicalize_identifier("STOCK", "TCS") -> "STOCK_TCS"
    """
    clean_id = re.sub(r"[^A-Za-z0-9_.-]", "_", str(identifier).strip().upper())
    return f"{prefix.upper()}_{clean_id}"


generate_canonical_uid = canonicalize_identifier



def clean_corporate_tokens(name: str) -> str:
    """
    Extracts key sorting/matching tokens for deterministic corporate entity resolution.
    """
    if not name:
        return ""
    if re.search(r"\blife\s+insurance\s+corporation\b|\blic\b", name, re.I):
        return "lic"
    text = re.sub(r"\(.*?\)", " ", name.lower())
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    tokens = sorted([t for t in text.split() if t not in STOPWORDS_CORPORATE and len(t) > 1])
    return " ".join(tokens)

