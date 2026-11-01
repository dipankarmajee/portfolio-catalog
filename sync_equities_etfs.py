import os
import sqlite3
import io
import requests
import pandas as pd
from datetime import datetime
import yfinance as yf

DB_PATH = os.path.join("data", "master_equities_etfs.sqlite")
os.makedirs("data", exist_ok=True)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS market_instruments (
            uid TEXT PRIMARY KEY,
            category TEXT NOT NULL,
            name TEXT NOT NULL,
            symbol_or_code TEXT NOT NULL,
            isin TEXT,
            issuer TEXT,
            latest_nav REAL,
            nav_date TEXT,
            status TEXT NOT NULL,
            last_synced_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

def sync():
    init_db()
    print("[Markets] Ingesting Equities, ETFs, and SGBs...")
    now_iso = datetime.now().isoformat()
    today_str = datetime.now().strftime("%d-%b-%Y")
    records = []

    # 1. Official NSE Equities Directory
    try:
        url = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code == 200:
            df = pd.read_csv(io.StringIO(resp.text))
            for _, row in df.iterrows():
                sym = str(row["SYMBOL"]).strip()
                name = str(row["NAME OF COMPANY"]).strip()
                isin = str(row["ISIN NUMBER"]).strip()
                records.append({
                    "uid": f"STOCK_{sym}",
                    "category": "STOCK",
                    "name": name,
                    "symbol_or_code": f"{sym}.NS",
                    "isin": isin,
                    "issuer": "NSE India",
                    "latest_nav": None,
                    "nav_date": today_str
                })
            print(f"[Markets] Parsed {len(records)} listed equities from NSE directory.")
    except Exception as e:
        print(f"[Markets] NSE Directory direct fetch fallback triggered: {e}")

    # Fallback core bluechips if remote CSV blocks CI
    if len(records) == 0:
        core_equities = [
            ("RELIANCE", "Reliance Industries Limited", "INE002A01018"),
            ("TCS", "Tata Consultancy Services Limited", "INE467B01029"),
            ("HDFCBANK", "HDFC Bank Limited", "INE040A01034"),
            ("INFY", "Infosys Limited", "INE009A01021"),
            ("TATAMOTORS", "Tata Motors Limited", "INE155A01022"),
            ("ITC", "ITC Limited", "INE154A01025"),
            ("ICICIBANK", "ICICI Bank Limited", "INE090A01021"),
            ("SBIN", "State Bank of India", "INE062A01020")
        ]
        for sym, name, isin in core_equities:
            records.append({
                "uid": f"STOCK_{sym}",
                "category": "STOCK",
                "name": name,
                "symbol_or_code": f"{sym}.NS",
                "isin": isin,
                "issuer": "NSE India",
                "latest_nav": None,
                "nav_date": today_str
            })

    # 2. Key ETFs
    etf_list = [
        ("NIFTYBEES", "Nippon India Nifty 50 BeES ETF", "INF204KB14I2"),
        ("BANKBEES", "Nippon India Nifty Bank BeES ETF", "INF204KB14L6"),
        ("GOLDBEES", "Nippon India ETF Gold BeES", "INF732E01037"),
        ("SILVERBEES", "Nippon India Silver ETF", "INF204KB19R0"),
        ("JUNIORBEES", "Nippon India Nifty Next 50 Junior BeES ETF", "INF204K01016")
    ]
    for sym, name, isin in etf_list:
        records.append({
            "uid": f"ETF_{sym}",
            "category": "ETF",
            "name": name,
            "symbol_or_code": f"{sym}.NS",
            "isin": isin,
            "issuer": "NSE India",
            "latest_nav": None,
            "nav_date": today_str
        })

    # 3. Sovereign Gold Bonds (Active Tranches)
    sgb_list = [
        ("SGBMAY29", "Sovereign Gold Bond 2021-22 Series I", "IN0020210053"),
        ("SGBDE28", "Sovereign Gold Bond 2020-21 Series IX", "IN0020200377"),
        ("SGBJA29", "Sovereign Gold Bond 2020-21 Series X", "IN0020200385"),
        ("SGBMR30", "Sovereign Gold Bond 2021-22 Series X", "IN0020210210")
    ]
    for sym, name, isin in sgb_list:
        records.append({
            "uid": f"SGB_{sym}",
            "category": "SGB",
            "name": name,
            "symbol_or_code": f"{sym}.NS",
            "isin": isin,
            "issuer": "Reserve Bank of India",
            "latest_nav": None,
            "nav_date": today_str
        })

    # 4. Fetch Closing Prices for Core / Monitored Instruments
    symbols_to_price = [r["symbol_or_code"] for r in records if r["category"] in ("ETF", "SGB") or r["uid"] in ("STOCK_RELIANCE", "STOCK_TCS", "STOCK_TATAMOTORS")]
    for sym in symbols_to_price:
        try:
            ticker = yf.Ticker(sym)
            hist = ticker.history(period="5d")
            if not hist.empty:
                last_price = round(float(hist["Close"].iloc[-1]), 2)
                for r in records:
                    if r["symbol_or_code"] == sym:
                        r["latest_nav"] = last_price
        except Exception as e:
            print(f"Pricing notice for {sym}: {e}")

    # 5. Database Upsert
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    for r in records:
        params = (r["uid"], r["category"], r["name"], r["symbol_or_code"], r.get("isin"), r["issuer"], r["latest_nav"], r["nav_date"], now_iso)
        cur.execute("""
            INSERT INTO market_instruments (uid, category, name, symbol_or_code, isin, issuer, latest_nav, nav_date, status, last_synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?)
            ON CONFLICT(uid) DO UPDATE SET
                name=excluded.name,
                isin=excluded.isin,
                latest_nav=coalesce(excluded.latest_nav, market_instruments.latest_nav),
                nav_date=excluded.nav_date,
                status='ACTIVE',
                last_synced_at=excluded.last_synced_at
        """, params)

    conn.commit()
    conn.close()
    print(f"[Markets] Completed upsert for {len(records)} records.")

if __name__ == "__main__":
    sync()
