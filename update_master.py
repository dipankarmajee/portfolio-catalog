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
    cur.execute("CREATE TABLE IF NOT EXISTS master_assets (uid TEXT PRIMARY KEY, category TEXT NOT NULL, name TEXT NOT NULL, symbol_or_code TEXT NOT NULL, issuer TEXT, latest_nav REAL, nav_date TEXT, status TEXT NOT NULL, last_synced_at TEXT NOT NULL)")
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
        params = (uid, r["category"], r["name"], r["symbol_or_code"], r.get("issuer"), r.get("latest_nav"), r.get("nav_date"), now_iso)
        cur.execute("INSERT INTO master_assets (uid, category, name, symbol_or_code, issuer, latest_nav, nav_date, status, last_synced_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?) ON CONFLICT(uid) DO UPDATE SET name=excluded.name, latest_nav=excluded.latest_nav, nav_date=excluded.nav_date, status='ACTIVE', last_synced_at=excluded.last_synced_at", params)
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
    print("[Mutual Funds] Downloading AMFI feed...")
    url = "https://www.amfiindia.com/spages/NAVAll.txt"
    resp = requests.get(url, headers=HEADERS, timeout=25)
    records = []
    for line in resp.text.splitlines():
        line = line.strip()
        if not line or ";" not in line or line.startswith("Scheme Code"):
            continue
        cols = [c.strip() for c in line.split(";")]
        if len(cols) >= 6:
            code = cols[0]
            scheme_name = cols[3]
            try:
                nav = float(cols[4])
            except ValueError:
                nav = None
            date_val = cols[5]
            records.append({"uid": f"MF_{code}", "category": "MUTUAL_FUND", "name": scheme_name, "symbol_or_code": code, "issuer": "AMFI Registered AMC", "latest_nav": nav, "nav_date": date_val})
    return records

def fetch_equities_and_etfs():
    print("[Equities & ETFs] Fetching NSE core instruments...")
    symbols = ["RELIANCE.NS", "TATAMOTORS.NS", "NIFTYBEES.NS", "GOLDBEES.NS", "SILVERBEES.NS"]
    records = []
    tickers = yf.Tickers(" ".join(symbols))
    for sym in symbols:
        try:
            t = tickers.tickers[sym]
            price = t.fast_info['last_price']
            is_etf = "BEES" in sym
            category = "ETF" if is_etf else "STOCK"
            records.append({"uid": f"{category}_{sym.replace('.NS', '')}", "category": category, "name": sym, "symbol_or_code": sym, "issuer": "NSE India", "latest_nav": float(price), "nav_date": datetime.now().strftime("%d-%b-%Y")})
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
                    records.append({"uid": f"INSURER_{val}", "category": "INSURER", "name": text_name, "symbol_or_code": val, "issuer": "IRDAI", "latest_nav": None, "nav_date": datetime.now().strftime("%d-%b-%Y")})
    except Exception as e:
        print(f"Council fetch error: {e}")
    return records

if __name__ == "__main__":
    print(f"=== Starting Ingestion: {datetime.now()} ===")
    init_db()
    mf_data = fetch_mutual_funds()
    upsert_records(mf_data, "MUTUAL_FUND")
    market_data = fetch_equities_and_etfs()
    upsert_records(market_data, "STOCK")
    upsert_records([r for r in market_data if r["category"] == "ETF"], "ETF")
    insurer_data = fetch_ulip_insurers()
    upsert_records(insurer_data, "INSURER")
    print("=== Master Ingestion Completed Successfully ===")
