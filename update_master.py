import os
import sqlite3
from datetime import datetime
import requests
import yfinance as yf
from bs4 import BeautifulSoup

DB_PATH = os.path.join("data", "master_catalog.sqlite")
os.makedirs("data", exist_ok=True)
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS master_assets (
            uid TEXT PRIMARY KEY,
            category TEXT NOT NULL,
            name TEXT NOT NULL,
            symbol_or_code TEXT NOT NULL,
            issuer TEXT,
            latest_nav REAL,
            nav_date TEXT,
            status TEXT NOT NULL,
            last_synced_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

def upsert_records(records, category):
    if not records:
        print(f"[{category}] No records fetched, skipping.")
        return
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    now_iso = datetime.now().isoformat()
    fetched_uids = set()

    for r in records:
        uid = r["uid"]
        fetched_uids.add(uid)
        params = (
            uid,
            r["category"],
            r["name"],
            r["symbol_or_code"],
            r.get("issuer"),
            r.get("latest_nav"),
            r.get("nav_date"),
            now_iso
        )
        cur.execute("""
            INSERT INTO master_assets (uid, category, name, symbol_or_code, issuer, latest_nav, nav_date, status, last_synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?)
            ON CONFLICT(uid) DO UPDATE SET
                name=excluded.name,
                latest_nav=excluded.latest_nav,
                nav_date=excluded.nav_date,
                status='ACTIVE',
                last_synced_at=excluded.last_synced_at
        """, params)

    cur.execute("SELECT uid FROM master_assets WHERE category = ? AND status = 'ACTIVE'", (category,))
    current_active = {row[0] for row in cur.fetchall()}
    missing_uids = current_active - fetched_uids

    if missing_uids:
        deact_params = [(now_iso, uid) for uid in missing_uids]
        cur.executemany("UPDATE master_assets SET status = 'DEACTIVATED', last_synced_at = ? WHERE uid = ?", deact_params)
        print(f"[{category}] Deactivated {len(missing_uids)} missing records.")

    conn.commit()
    conn.close()
    print(f"[{category}] Successfully processed {len(records)} records.")

def fetch_mutual_funds():
    print("[Mutual Funds] Downloading and parsing AMFI feed...")
    url = "https://www.amfiindia.com/spages/NAVAll.txt"
    resp = requests.get(url, headers=HEADERS, timeout=30)
    records = []

    for line in resp.text.splitlines():
        line = line.strip()
        if not line or ";" not in line or line.startswith("Scheme Code"):
            continue
        cols = [c.strip() for c in line.split(";")]
        
        # AMFI standard structure:
        # cols[0]: Scheme Code
        # cols[1]: ISIN Div Payout / ISIN Growth
        # cols[2]: ISIN Div Reinvestment
        # cols[3]: Scheme Name
        # cols[-2]: Net Asset Value
        # cols[-1]: Date
        if len(cols) >= 5:
            code = cols[0]
            if not code.isdigit():
                continue
            
            # The last element is always Date, second last is always NAV
            date_val = cols[-1]
            raw_nav = cols[-2]
            
            # Scheme name sits between ISINs and NAV
            scheme_name = cols[3] if len(cols) == 6 else " ".join(cols[3:-2])
            
            try:
                nav = float(raw_nav)
            except ValueError:
                nav = None
                
            records.append({
                "uid": f"MF_{code}",
                "category": "MUTUAL_FUND",
                "name": scheme_name,
                "symbol_or_code": code,
                "issuer": "AMFI Registered AMC",
                "latest_nav": nav,
                "nav_date": date_val
            })
    return records

def fetch_market_instruments():
    print("[Markets] Fetching Equities, ETFs, and SGBs...")
    
    # Core Bluechip Equities + Major ETFs + Active SGBs
    equities = ["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "TATAMOTORS.NS", "ITC.NS", "ICICIBANK.NS", "SBIN.NS"]
    etfs = ["NIFTYBEES.NS", "BANKBEES.NS", "GOLDBEES.NS", "SILVERBEES.NS", "JUNIORBEES.NS"]
    sgbs = ["SGBMAY29.NS", "SGBDE28.NS", "SGBJA29.NS", "SGBMR30.NS"]
    
    all_symbols = equities + etfs + sgbs
    records = []
    
    for sym in all_symbols:
        try:
            t = yf.Ticker(sym)
            fast = t.fast_info
            price = fast.get("last_price") or fast.get("previous_close")
            if price is None:
                continue
                
            if sym in equities:
                category = "STOCK"
            elif sym in etfs:
                category = "ETF"
            else:
                category = "SGB"

            clean_sym = sym.replace(".NS", "")
            records.append({
                "uid": f"{category}_{clean_sym}",
                "category": category,
                "name": sym,
                "symbol_or_code": sym,
                "issuer": "NSE India" if category != "SGB" else "Reserve Bank of India",
                "latest_nav": float(price),
                "nav_date": datetime.now().strftime("%d-%b-%Y")
            })
        except Exception as e:
            print(f"Error fetching {sym}: {e}")
            
    return records

def fetch_ulip_insurers():
    print("[ULIPs] Querying Life Insurance Council directory...")
    url = "https://www.lifeinscouncil.org/industry%20information/ListOfFundNAVs"
    records = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(resp.text, "html.parser")
        dropdown = soup.find("select", {"id": "MainContent_drpselectinscompany"})
        if dropdown:
            for opt in dropdown.find_all("option"):
                val = opt.get("value")
                text_name = opt.text.strip()
                if val and val != "0" and "--Select" not in text_name:
                    records.append({
                        "uid": f"INSURER_{val}",
                        "category": "INSURER",
                        "name": text_name,
                        "symbol_or_code": val,
                        "issuer": "IRDAI",
                        "latest_nav": None,
                        "nav_date": datetime.now().strftime("%d-%b-%Y")
                    })
    except Exception as e:
        print(f"Council fetch error: {e}")
    return records

if __name__ == "__main__":
    print(f"=== Starting Ingestion: {datetime.now()} ===")
    init_db()

    # 1. Mutual Funds (AMFI)
    mf_data = fetch_mutual_funds()
    upsert_records(mf_data, "MUTUAL_FUND")

    # 2. Market Instruments (Equities, ETFs, SGBs)
    market_data = fetch_market_instruments()
    upsert_records([r for r in market_data if r["category"] == "STOCK"], "STOCK")
    upsert_records([r for r in market_data if r["category"] == "ETF"], "ETF")
    upsert_records([r for r in market_data if r["category"] == "SGB"], "SGB")

    # 3. Insurers
    insurer_data = fetch_ulip_insurers()
    upsert_records(insurer_data, "INSURER")

    print("=== Master Ingestion Completed Successfully ===")
