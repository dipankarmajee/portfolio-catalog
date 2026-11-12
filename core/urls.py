"""
core/urls.py
Centralized registry of official government, regulatory, exchange,
and market feed endpoint URLs.
"""

# Equities, ETFs & SGBs (India & World)
NSE_HOME_URL = "https://www.nseindia.com"
NSE_EQUITIES_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
NSE_ETF_URL = "https://archives.nseindia.com/content/equities/eq_etfseclist.csv"
NSE_BHAVCOPY_BASE_URL = "https://archives.nseindia.com/products/content/sec_bhavdata_full_{date}.csv"
SEC_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

# Mutual Funds (India & World)
AMFI_NAV_ALL_URL = "https://www.amfiindia.com/spages/NAVAll.txt"

# National Pension System (NPS)
NPS_TRUST_NAV_URL = "https://www.npstrust.org.in/daily-nav"
NPS_LATEST_API_URL = "https://npsnav.in/api/latest"
NPS_SCHEMES_API_URL = "https://npsnav.in/api/schemes"

# Precious Metals (Gold, Silver, Platinum)
IBJA_HOME_URL = "https://www.ibja.co/"
IBJA_RATES_PORTAL_URL = "https://ibjarates.com/"
GLOBAL_SPOT_GOLD_URL = "https://query1.finance.yahoo.com/v8/finance/chart/GC=F"
GLOBAL_SPOT_SILVER_URL = "https://query1.finance.yahoo.com/v8/finance/chart/SI=F"

# Crypto
COINGECKO_TOP_URL = (
    "https://api.coingecko.com/api/v3/coins/markets"
    "?vs_currency=inr&order=market_cap_desc&per_page=100&page=1&sparkline=false"
    "&price_change_percentage=24h"
)
COINCAP_ASSETS_URL = "https://api.coincap.io/v2/assets?limit=100"
USD_INR_EXCHANGE_RATE_URL = "https://query1.finance.yahoo.com/v8/finance/chart/USDINR=X"

# Insurers & ULIPs
IRDAI_PORTAL_ROOT = "https://irdai.gov.in"
IRDAI_LIFE_INSURERS_URL = "https://irdai.gov.in/list-of-life-insurers1"
IRDAI_LIFE_PRODUCTS_URL = (
    "https://irdai.gov.in/list-of-life-products"
    "?p_p_id=com_irdai_document_media_IRDAIDocumentMediaPortlet&p_p_lifecycle=0"
    "&p_p_state=normal&p_p_mode=view"
    "&_com_irdai_document_media_IRDAIDocumentMediaPortlet_delta=60"
    "&_com_irdai_document_media_IRDAIDocumentMediaPortlet_resetCur=false"
)
LIFE_COUNCIL_NAV_URL = "https://www.lifeinscouncil.org/industry%20information/list_of_fund_NAVs.aspx"
IRDAI_LIFE_PRODUCTS_LIST_URL = "https://irdai.gov.in/list-of-products-life"
IRDAI_LIFE_PRODUCTS_ALT_URL = "https://irdai.gov.in/web/guest/list-of-products-life"
LIFE_COUNCIL_UIN_URL = "https://www.lifeinscouncil.org/industry%20information/UINdetails.aspx"

# Fixed Income (Indian Small Savings, US Treasuries, RBI Policy Rates)
NSI_PORTAL_ROOT = "https://www.nsiindia.gov.in"
NSI_SCHEMES_RATES_URL = "https://www.nsiindia.gov.in/InternalPage.aspx?Id_Pk=132"
NSI_SCHEMES_OVERVIEW_URL = "https://www.nsiindia.gov.in/InternalPage.aspx?Id_Pk=27"
US_TREASURY_YIELD_CURVE_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
    "?data=daily_treasury_yield_curve&field_tdr_date_value={year}"
)
RBI_HOME_URL = "https://www.rbi.org.in/"
