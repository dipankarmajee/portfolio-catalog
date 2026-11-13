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
    3. Strips leading slash/punctuation artifacts (e.g. './', '/', '.\\', '-')
    4. Normalizes whitespace
    """
    if not text:
        return ""
    # Normalize unicode
    normalized = unicodedata.normalize("NFKD", str(text))
    # Remove Devanagari script
    stripped = DEVANAGARI_PATTERN.sub(" ", normalized)
    # Remove leading dots, slashes, backslashes, dashes, bullets or stray symbols
    cleaned = re.sub(r"^[./\\\s\-•*|~>]+", "", stripped)
    # Collapse multiple whitespaces
    return WHITESPACE_PATTERN.sub(" ", cleaned).strip()


def strip_punctuation_prefix(text: Optional[str]) -> str:
    """Strips leading ./, /, .\\, -, •, or spaces from text."""
    if not text:
        return ""
    cleaned = re.sub(r"^[./\\\s\-•*|~>]+", "", str(text))
    return WHITESPACE_PATTERN.sub(" ", cleaned).strip()


def strip_trailing_punctuation(text: Optional[str]) -> str:
    """Strips trailing punctuation (dots, colons, semicolons, commas, dashes, slashes, whitespace)."""
    if not text:
        return ""
    return re.sub(r"[\s.,;:/\-]+$", "", str(text)).strip()


def clean_company_name(name: Optional[str]) -> str:
    """
    Cleans and standardizes company names:
    - Strips leading punctuation and path prefixes (e.g. './', '/')
    - Strips trailing dots or replaces trailing 'Company.' with 'Co. Ltd.'
    - Normalizes abbreviations (e.g. 'Co. Ltd.', 'Pvt. Ltd.')
    """
    if not name:
        return ""
    s = strip_punctuation_prefix(clean_english_text(name))
    
    # Normalize internal company tokens
    s = re.sub(r"\bCo\s*\.\s*Ltd\b\.?", "Co. Ltd.", s, flags=re.I)
    s = re.sub(r"\bPvt\s*\.\s*Ltd\b\.?", "Pvt. Ltd.", s, flags=re.I)
    s = re.sub(r"\bCompany\b\.?$", "Co. Ltd.", s, flags=re.I)
    s = re.sub(r"\bCompany\s+Limited\b\.?$", "Co. Ltd.", s, flags=re.I)
    s = re.sub(r"\bCompany\s+Ltd\b\.?$", "Co. Ltd.", s, flags=re.I)
    s = re.sub(r"\bCo\s+Ltd\b\.?$", "Co. Ltd.", s, flags=re.I)
    s = re.sub(r"\bLimited\b\.?$", "Limited", s, flags=re.I)

    if s.endswith("Co. Ltd.") or s.endswith("Pvt. Ltd."):
        pass
    elif s.endswith("Co. Ltd") or s.endswith("Pvt. Ltd"):
        s = s + "."
    else:
        s = strip_trailing_punctuation(s)

    return WHITESPACE_PATTERN.sub(" ", s).strip()


def extract_clean_brand(insurer_name: Optional[str]) -> str:
    """Extracts short brand name from an insurer's full name."""
    cleaned = clean_company_name(insurer_name)
    if not cleaned:
        return ""
    if "Life Insurance Corporation" in cleaned or cleaned.upper() == "LIC":
        return "LIC"

    brand = cleaned
    for suffix in (
        " Insurance Company Limited", " Insurance Company Ltd.", " Insurance Co. Ltd.",
        " Life Insurance Company Limited", " Life Insurance Company Ltd.", " Life Insurance Co. Ltd.",
        " Life Insurance Limited", " Company Limited", " Insurance Limited",
        " Co. Ltd.", " Pvt. Ltd.", " Limited", " Ltd."
    ):
        if suffix.lower() in brand.lower():
            idx = brand.lower().find(suffix.lower())
            brand = brand[:idx]
            break
    return strip_trailing_punctuation(brand)


def build_canonical_insurance_name(insurer_name: Optional[str], product_or_fund_name: Optional[str]) -> str:
    """
    Builds clean canonical display title: '<Insurer Clean Name> - <Product Marketing Name>'.
    Ensures brand prefix is clean and not duplicated.
    """
    brand = extract_clean_brand(insurer_name)
    raw = strip_trailing_punctuation(strip_punctuation_prefix(clean_english_text(product_or_fund_name)))
    clean_item = raw.title() if raw.isupper() else raw

    if not brand:
        return clean_item
    if not clean_item:
        return brand

    if clean_item.lower().startswith(brand.lower()):
        return clean_item
    return f"{brand} - {clean_item}"


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

