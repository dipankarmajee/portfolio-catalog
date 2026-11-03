# Portfolio Catalog Master

An automated, local-first master catalog and daily ingestion engine for Indian and global financial instruments. Designed for offline portfolio trackers, accounting tools, and personal finance applications.

---

## 🌟 Supported Asset Classes

| Asset Class | Coverage & Markets | Authoritative Sources | Captured Attributes |
| :--- | :--- | :--- | :--- |
| **Stocks & Equities** | India (NSE) & US / Global (SEC EDGAR) | Official NSE Directory & US SEC EDGAR (`sec.gov`) | Symbol, Ticker, Name, ISIN/CIK, Exchange, Currency, Status |
| **Mutual Funds** | India (AMFI) & Global Indexes | Association of Mutual Funds in India (AMFI) | Scheme Code, ISIN (Growth/Payout/Reinv), AMC Name, Category, NAV, Date |
| **ETFs** | India & World | NSE ETF Master & US SEC Directory | Symbol, Name, Category, Benchmark, Exchange, Currency |
| **Fixed Income** | India (Government Small Savings, EPF, SGB, Bank FDs) & US Treasuries | Ministry of Finance, EPFO, RBI, SBI Card Rates, US Treasury | Scheme Code, Annual Interest Rate, Compounding Frequency, Payout Schedule, Tenure, Tax Status (EEE, 80C) |
| **NPS** | National Pension System (PFRDA) | NPS Trust (`npstrust.org.in`) | PFM Name, Scheme Code, Asset Class (E, C, G, A), Tier I & II, Daily NAV |
| **Precious Metals** | Gold (24K, 22K, 18K) & Silver | India Bullion & Jewellers Association (IBJA) + LBMA | Purity (999, 995, 916), Measurement Unit, Benchmark Spot Rate, Currency (INR/USD) |
| **Crypto Assets** | Top Liquid Digital Assets | CoinGecko / CoinCap Market Feeds | Symbol, Name, Market Cap Rank, Price in INR & USD, 24h High/Low, 24h Change |
| **ULIPs & Insurers** | IRDAI Regulated Entities & ULIP SFINs | Life Insurance Council & IRDAI Registries | SFIN, Fund Name, Commercial Plan Name, UIN, Insurer Name, Inception Date, High/Low/Avg |

---

## 🏗️ Architecture & Directory Structure

```text
portfolio-catalog/
├── core/                         # Shared core framework & utilities
│   ├── config.py                 # Filepaths, default timeouts, user-agents
│   ├── enums.py                  # Domain enums (AssetClass, Country, Currency, Exchange, Status)
│   ├── urls.py                   # Centralized official source endpoint registry
│   ├── http_client.py            # Resilient HTTP requests with backoff retries & connection pooling
│   ├── text_utils.py             # English-only normalization, Devanagari stripping, identifier builder
│   ├── database.py               # Optimized SQLite connection manager (WAL mode) & schema docs
│   └── exceptions.py             # Custom exceptions
├── modules/                      # Domain-isolated data ingestion modules
│   ├── equities/                 # NSE listed equities & US SEC EDGAR public companies
│   │   ├── nse_collector.py
│   │   └── sec_edgar_collector.py
│   ├── mutual_funds/             # AMFI mutual fund daily NAV stream & classifications
│   │   └── amfi_collector.py
│   ├── fixed_income/             # PPF, SSY, EPF, SCSS, NSC, KVP, SGB, Bank FDs, US Treasuries
│   │   └── fixed_income_collector.py
│   ├── nps/                      # PFRDA Pension Fund Managers (Schemes E, C, G, A)
│   │   └── nps_collector.py
│   ├── commodities/              # IBJA official gold (999, 916) and silver benchmarks
│   │   └── ibja_collector.py
│   ├── crypto/                   # Major cryptocurrencies & stablecoins in USD and INR
│   │   └── crypto_collector.py
│   └── ulips/                    # IRDAI entities, life insurers, and Life Council ULIP funds
│       ├── irdai_entities.py
│       ├── life_council.py
│       ├── commercial_plans.py
│       └── ulip_collector.py
├── data/                         # Local SQLite master catalogs
│   ├── master_equities_etfs.sqlite
│   ├── master_mutual_funds.sqlite
│   ├── master_fixed_income.sqlite
│   ├── master_nps.sqlite
│   ├── master_commodities_crypto.sqlite
│   └── master_insurers_ulips.sqlite
├── documentation/
│   └── DATABASE_SCHEMA.md        # Comprehensive auto-generated catalog report
├── tests/                        # Automated unit & schema test suite
├── orchestrator.py               # Master CLI entry point
└── .github/workflows/
    └── daily_update.yml          # Automated GitHub Actions workflow (11:30 PM IST daily)
```

---

## 🚀 Usage & Execution

### 1. Install Dependencies
```bash
python -m pip install -r requirements.txt
```

### 2. Run Master Orchestrator
```bash
# Run the entire master catalog sync across all asset classes
python orchestrator.py --all

# Run a specific domain module
python orchestrator.py --module equities
python orchestrator.py --module mutual_funds
python orchestrator.py --module fixed_income
python orchestrator.py --module nps
python orchestrator.py --module commodities
python orchestrator.py --module crypto
python orchestrator.py --module ulips

# Regenerate schema documentation only
python orchestrator.py --docs
```

### 3. Run Automated Tests
```bash
python -m unittest discover -s tests -v
```

---

## ⏰ Automated GitHub Actions Workflow

The workflow at `.github/workflows/daily_update.yml` runs automatically Monday through Friday at **11:30 PM IST** (`18:00 UTC`), updates the local SQLite catalogs, regenerates `documentation/DATABASE_SCHEMA.md`, and commits the updated catalogs back to the repository.
