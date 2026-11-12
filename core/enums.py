"""
core/enums.py
Central domain enumerations for asset classes, currencies, countries,
frequencies, tax treatments, and instrument classifications.
"""

from enum import Enum


class AssetClass(str, Enum):
    STOCK = "STOCK"
    ETF = "ETF"
    MUTUAL_FUND = "MUTUAL_FUND"
    FIXED_INCOME = "FIXED_INCOME"
    NPS = "NPS"
    COMMODITY = "COMMODITY"
    CRYPTO = "CRYPTO"
    ULIP = "ULIP"
    REIT_INVIT = "REIT_INVIT"
    SGB = "SGB"
    INSURANCE_PRODUCT = "INSURANCE_PRODUCT"


class Country(str, Enum):
    INDIA = "IND"
    UNITED_STATES = "USA"
    GLOBAL = "GLOBAL"


class Currency(str, Enum):
    INR = "INR"
    USD = "USD"


class Exchange(str, Enum):
    NSE = "NSE"
    BSE = "BSE"
    NASDAQ = "NASDAQ"
    NYSE = "NYSE"
    AMEX = "AMEX"
    OTC = "OTC"
    GLOBAL = "GLOBAL"


class InstrumentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    SUSPENDED = "SUSPENDED"
    MATURED = "MATURED"
    CLOSED = "CLOSED"


class CompoundingFrequency(str, Enum):
    ANNUAL = "ANNUAL"
    SEMI_ANNUAL = "SEMI_ANNUAL"
    QUARTERLY = "QUARTERLY"
    MONTHLY = "MONTHLY"
    DAILY = "DAILY"
    SIMPLE = "SIMPLE"
    NOT_APPLICABLE = "N/A"


class PayoutFrequency(str, Enum):
    AT_MATURITY = "AT_MATURITY"
    ANNUAL = "ANNUAL"
    SEMI_ANNUAL = "SEMI_ANNUAL"
    QUARTERLY = "QUARTERLY"
    MONTHLY = "MONTHLY"
    NOT_APPLICABLE = "N/A"


class TaxTreatment(str, Enum):
    EEE = "EEE"           # Exempt, Exempt, Exempt (e.g. PPF, SSY)
    EET = "EET"           # Exempt on contribution/interest, Taxed on withdrawal
    TAXABLE = "TAXABLE"
    SEC_80C = "SEC_80C"


class FixedIncomeCategory(str, Enum):
    SMALL_SAVINGS = "SMALL_SAVINGS"
    RETIREMENT = "RETIREMENT"
    SOVEREIGN_GOLD_BOND = "SOVEREIGN_GOLD_BOND"
    SOVEREIGN_BOND = "SOVEREIGN_BOND"
    BANK_DEPOSIT = "BANK_DEPOSIT"
    TREASURY_BILL = "TREASURY_BILL"
    GOVERNMENT_SECURITY = "GOVERNMENT_SECURITY"
    CORPORATE_BOND = "CORPORATE_BOND"
    POLICY_RATE = "POLICY_RATE"


class NpsTier(str, Enum):
    TIER_I = "TIER_I"
    TIER_II = "TIER_II"
    ALL_CITIZEN = "ALL_CITIZEN"
    CORPORATE = "CORPORATE"
    GOVERNMENT = "GOVERNMENT"


class NpsAssetClass(str, Enum):
    E = "E"   # Equity
    C = "C"   # Corporate Debt
    G = "G"   # Government Securities
    A = "A"   # Alternative Investment Funds
    ALL = "ALL"


class CommodityType(str, Enum):
    GOLD = "GOLD"
    SILVER = "SILVER"
    PLATINUM = "PLATINUM"


class CommodityUnit(str, Enum):
    GRAM_10 = "10_GRAMS"
    KG_1 = "1_KG"
    TROY_OUNCE = "TROY_OUNCE"


class CommodityPurity(str, Enum):
    PURITY_999 = "999 (24K)"
    PURITY_995 = "995 (24K)"
    PURITY_916 = "916 (22K)"
    PURITY_750 = "750 (18K)"
    PURITY_585 = "585 (14K)"


class InsurerCategory(str, Enum):
    LIFE_INSURERS = "LIFE_INSURERS"


class UlipCategory(str, Enum):
    EQUITY = "EQUITY"
    DEBT = "DEBT"
    BALANCED = "BALANCED"
    MONEY_MARKET = "MONEY_MARKET"
    PENSION = "PENSION"
    DISCONTINUED = "DISCONTINUED"
    OTHER = "OTHER"


class UlipFundType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    GROUP = "GROUP"
    DISCONTINUED = "DISCONTINUED"

