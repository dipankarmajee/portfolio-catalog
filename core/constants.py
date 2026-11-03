"""
core/constants.py
Centralized domain constants, regex patterns, token vocabularies,
and statutory instrument mapping registries across all asset modules.
"""

import re
from typing import Dict, List, Set, Tuple

from core.enums import (
    CommodityPurity,
    CommodityType,
    CommodityUnit,
    CompoundingFrequency,
    FixedIncomeCategory,
    NpsAssetClass,
    NpsTier,
    PayoutFrequency,
    TaxTreatment,
)

# =====================================================================
# 1. Text & Regex Normalization Patterns
# =====================================================================

DEVANAGARI_PATTERN = re.compile(r"[\u0900-\u097F]+")
WHITESPACE_PATTERN = re.compile(r"\s+")
URL_EXTRACT_PATTERN = re.compile(r"(?:https?://|www\.)[^\s,;<>\"']+", re.I)

# Corporate legal tokens to strip when normalizing corporate company entities
STOPWORDS_CORPORATE: Set[str] = {
    "company", "co", "limited", "ltd", "pvt", "private",
    "corporation", "corp", "insurance", "life", "of", "india",
    "services", "ins", "general", "assurance"
}

# =====================================================================
# 2. Equities & ETFs Constants
# =====================================================================

# NSE trading series to exclude (SME / Trade-to-Trade / Suspended)
NSE_EXCLUDED_SERIES: Tuple[str, ...] = ("SM", "ST")

# =====================================================================
# 3. Fixed Income Statutory Mappings & Scraper Patterns
# =====================================================================

# National Savings Institute (NSI) Ministry of Finance small savings schemes
NSI_SCHEME_PATTERNS: List[Tuple] = [
    ("PPF", r"public\s+provident\s+fund", "Public Provident Fund", 180, 0, 500.0, 150000.0,
     CompoundingFrequency.ANNUAL.value, PayoutFrequency.AT_MATURITY.value, TaxTreatment.EEE.value, "80C, 10(11)"),
    ("SSY", r"sukanya\s+samriddhi", "Sukanya Samriddhi Account", 252, 252, 250.0, 150000.0,
     CompoundingFrequency.ANNUAL.value, PayoutFrequency.AT_MATURITY.value, TaxTreatment.EEE.value, "80C, 10(11A)"),
    ("SCSS", r"senior\s+citizen", "Senior Citizen Savings Scheme", 60, 96, 1000.0, 3000000.0,
     CompoundingFrequency.QUARTERLY.value, PayoutFrequency.QUARTERLY.value, TaxTreatment.TAXABLE.value, "80C"),
    ("NSC", r"national\s+savings?\s+certificate", "National Savings Certificate (VIII Issue)", 60, 60, 1000.0, 0.0,
     CompoundingFrequency.ANNUAL.value, PayoutFrequency.AT_MATURITY.value, TaxTreatment.TAXABLE.value, "80C"),
    ("KVP", r"kisan\s+vikas\s+patra", "Kisan Vikas Patra", 115, 115, 1000.0, 0.0,
     CompoundingFrequency.ANNUAL.value, PayoutFrequency.AT_MATURITY.value, TaxTreatment.TAXABLE.value, None),
    ("POMIS", r"monthly\s+income\s+account", "Post Office Monthly Income Scheme", 60, 60, 1000.0, 900000.0,
     CompoundingFrequency.MONTHLY.value, PayoutFrequency.MONTHLY.value, TaxTreatment.TAXABLE.value, None),
    ("POTD_1Y", r"1\s*year\s*time\s*deposit", "Post Office Time Deposit 1 Year", 12, 12, 1000.0, 0.0,
     CompoundingFrequency.QUARTERLY.value, PayoutFrequency.ANNUAL.value, TaxTreatment.TAXABLE.value, None),
    ("POTD_2Y", r"2\s*year\s*time\s*deposit", "Post Office Time Deposit 2 Year", 24, 24, 1000.0, 0.0,
     CompoundingFrequency.QUARTERLY.value, PayoutFrequency.ANNUAL.value, TaxTreatment.TAXABLE.value, None),
    ("POTD_3Y", r"3\s*year\s*time\s*deposit", "Post Office Time Deposit 3 Year", 36, 36, 1000.0, 0.0,
     CompoundingFrequency.QUARTERLY.value, PayoutFrequency.ANNUAL.value, TaxTreatment.TAXABLE.value, None),
    ("POTD_5Y", r"5\s*year\s*time\s*deposit", "Post Office Time Deposit 5 Year", 60, 60, 1000.0, 0.0,
     CompoundingFrequency.QUARTERLY.value, PayoutFrequency.ANNUAL.value, TaxTreatment.TAXABLE.value, "80C"),
    ("PORD", r"recurring\s*deposit", "Post Office Recurring Deposit", 60, 60, 100.0, 0.0,
     CompoundingFrequency.QUARTERLY.value, PayoutFrequency.AT_MATURITY.value, TaxTreatment.TAXABLE.value, None),
    ("POSA", r"savings?\s*account", "Post Office Savings Account", 0, 0, 500.0, 0.0,
     CompoundingFrequency.ANNUAL.value, PayoutFrequency.ANNUAL.value, TaxTreatment.TAXABLE.value, "80TTA"),
]

# Reserve Bank of India policy benchmarks
RBI_RATE_TARGETS: List[Tuple[str, str, str, str]] = [
    ("RBI_REPO_RATE", r"policy\s+repo\s+rate", "RBI Policy Repo Rate", FixedIncomeCategory.POLICY_RATE.value),
    ("RBI_BANK_RATE", r"bank\s+rate", "RBI Bank Rate Benchmark", FixedIncomeCategory.POLICY_RATE.value),
    ("RBI_REVERSE_REPO", r"reverse\s+repo\s+rate", "RBI Fixed Reverse Repo Rate", FixedIncomeCategory.POLICY_RATE.value),
]

# US Treasury yield curve XML tag mappings
TREASURY_SERIES: List[Tuple[str, str, str, int, int]] = [
    ("US_TREASURY_1M", "US Treasury Bill 1 Month", "BC_1MONTH", 1, 1),
    ("US_TREASURY_3M", "US Treasury Bill 3 Month", "BC_3MONTH", 3, 3),
    ("US_TREASURY_6M", "US Treasury Bill 6 Month", "BC_6MONTH", 6, 6),
    ("US_TREASURY_1Y", "US Treasury Note 1 Year", "BC_1YEAR", 12, 12),
    ("US_TREASURY_2Y", "US Treasury Note 2 Year", "BC_2YEAR", 24, 24),
    ("US_TREASURY_5Y", "US Treasury Note 5 Year", "BC_5YEAR", 60, 60),
    ("US_TREASURY_10Y", "US Treasury Bond 10 Year Benchmark", "BC_10YEAR", 120, 120),
    ("US_TREASURY_30Y", "US Treasury Long Bond 30 Year", "BC_30YEAR", 360, 360),
]

# =====================================================================
# 4. National Pension System (NPS) Classification
# =====================================================================

NPS_TIER_KEYWORDS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"TIER\s*[-–]?\s*II|TIER\s*2", re.I), NpsTier.TIER_II.value),
    (re.compile(r"CENTRAL\s+GOVT|STATE\s+GOVT", re.I), NpsTier.GOVERNMENT.value),
    (re.compile(r"CORPORATE", re.I), NpsTier.CORPORATE.value),
]

NPS_ASSET_CLASS_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"\bSCHEME\s+E\b|EQUITY", re.I), NpsAssetClass.E.value),
    (re.compile(r"\bSCHEME\s+C\b|CORPORATE\s+BOND", re.I), NpsAssetClass.C.value),
    (re.compile(r"\bSCHEME\s+G\b|GOVT", re.I), NpsAssetClass.G.value),
    (re.compile(r"\bSCHEME\s+A\b|ALTERNATIVE", re.I), NpsAssetClass.A.value),
]

# =====================================================================
# 5. Commodities & Precious Metals Metadata
# =====================================================================

BULLION_METADATA: Dict[str, Tuple[str, str, str, str, str]] = {
    "GOLD 999": ("GOLD_999_10G", "Gold 24K (999 Purity) - 10g", CommodityType.GOLD.value, CommodityPurity.PURITY_999.value, CommodityUnit.GRAM_10.value),
    "GOLD 995": ("GOLD_995_10G", "Gold 24K (995 Purity) - 10g", CommodityType.GOLD.value, CommodityPurity.PURITY_995.value, CommodityUnit.GRAM_10.value),
    "GOLD 916": ("GOLD_916_10G", "Gold 22K (916 Purity / Hallmark) - 10g", CommodityType.GOLD.value, CommodityPurity.PURITY_916.value, CommodityUnit.GRAM_10.value),
    "GOLD 750": ("GOLD_750_10G", "Gold 18K (750 Purity) - 10g", CommodityType.GOLD.value, CommodityPurity.PURITY_750.value, CommodityUnit.GRAM_10.value),
    "GOLD 585": ("GOLD_585_10G", "Gold 14K (585 Purity) - 10g", CommodityType.GOLD.value, CommodityPurity.PURITY_585.value, CommodityUnit.GRAM_10.value),
    "SILVER 999": ("SILVER_999_1KG", "Silver (999 Purity) - 1kg", CommodityType.SILVER.value, CommodityPurity.PURITY_999.value, CommodityUnit.KG_1.value),
    "PLATINUM 999": ("PLATINUM_999_10G", "Platinum (999 Purity) - 10g", CommodityType.PLATINUM.value, CommodityPurity.PURITY_999.value, CommodityUnit.GRAM_10.value),
}

# =====================================================================
# 6. Insurers & ULIPs Statutory Patterns & Keywords
# =====================================================================

SFIN_DATE_PATTERN = re.compile(r"(?:UL[A-Z0-9]{5}|DP[A-Z0-9]{5}|UNCL[A-Z0-9]{3})(\d{2})(\d{2})(\d{2})")

# Deterministic patterns for statutory asset categorization (Artos standard)
ULIP_DISCONTINUED_PATTERNS: Tuple[str, ...] = (
    "discontinued", "discont", "unclaimed", "dpf"
)

ULIP_PENSION_PATTERNS: Tuple[str, ...] = (
    "pension", "annuity", "retirement"
)

ULIP_MONEY_MARKET_PATTERNS: Tuple[str, ...] = (
    "money market", "moneymkt", "liquid", "cash", "floating", "treasury bill",
    "current", "short term", "short trm", "sto plus"
)

ULIP_BALANCED_PATTERNS: Tuple[str, ...] = (
    "balanced", "balanc", "hybrid", "managed", "dynamic", "multi asset",
    "asset alloc", "stabilizer", "aggressive", "moderate", "conservative",
    "prudent", "enhancer", "flexi", "stable", "stability", "moderator",
    "builder", "nourish", "enrich", "save n grow", "vantage", "conser"
)

ULIP_EQUITY_PATTERNS: Tuple[str, ...] = (
    "equity", "eqty", "growth", "grwth", "top 200", "top 100", "midcap", "mid cap",
    "smallcap", "small cap", "largecap", "large cap", "large-cap", "mid-cap", "small-cap",
    "multi-cap", "multicap", "top 50", "top 300", "top 500", "focus 50", "nifty", "index",
    "opportunities", "opportunity", "bluechip", "leaders", "leader", "multiplier", "discovery",
    "alpha", "infrastructure", "pharma", "tech", "focused", "futures", "select", "venture",
    "value", "special situations", "esg", "msci", "stock", "consumption", "manufacturing",
    "dividend yield", "mnc", "accelerat", "rising india", "make in india", "energy", "psu",
    "momentum", "multifactor", "maximiser", "maximizer", "maximus", "titanium", "platinum",
    "creator", "magnifier", "super 20", "apex", "pioneer", "crest", "summit", "prime", "pure eq"
)

ULIP_DEBT_PATTERNS: Tuple[str, ...] = (
    "debt", "bond", "income", "gilt", "secure", "defender", "treasury", "govt",
    "government", "fixed", "credit", "money plus", "secured", "protector", "savings",
    "sovereign", "preserv", "constant maturity", "capital protect", "guardian", "guarantee",
    "guaranteed", "assure"
)

