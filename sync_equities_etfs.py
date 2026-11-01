import os
import sqlite3
import math
from datetime import datetime
import requests
import yfinance as yf

DB_PATH = os.path.join("data", "master_equities_etfs.sqlite")
os.makedirs("data", exist_ok=True)
HEADERS = {"User-Agent": "Mozilla/5.0"}

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

def extract_price(symbol_variants):
    """Tries primary and alternate ticker representations across NSE/BSE to guarantee price resolution."""
    if isinstance(symbol_variants, str):
        symbol_variants = [symbol_variants]

    for sym in symbol_variants:
        try:
            t = yf.Ticker(sym)
            # Try 1-month history (catches low-frequency SGB trading days)
            hist = t.history(period="1mo")
            if not hist.empty:
                closes = hist["Close"].dropna()
                if not closes.empty:
                    val = float(closes.iloc[-1])
                    if not math.isnan(val) and val > 0:
                        return round(val, 2)

            # Try fast_info attributes
            for attr in ("last_price", "previous_close", "regular_market_price"):
                val = t.fast_info.get(attr)
                if val is not None and not math.isnan(float(val)) and float(val) > 0:
                    return round(float(val), 2)
        except Exception:
            continue
    return None

def sync():
    init_db()
    print("[Markets] Synchronizing Equities, ETFs, and Sovereign Gold Bonds...")
    now_iso = datetime.now().isoformat()
    today_str = datetime.now().strftime("%d-%b-%Y")
    records = []

    # 1. Equities (Including updated dual-listed symbols for demerged auto entities)
    equities = [
        ("RELIANCE", "Reliance Industries Limited", "INE002A01018", ["RELIANCE.NS", "RELIANCE.BO"]),
        ("TCS", "Tata Consultancy Services Limited", "INE467B01029", ["TCS.NS", "TCS.BO"]),
        ("HDFCBANK", "HDFC Bank Limited", "INE040A01034", ["HDFCBANK.NS", "HDFCBANK.BO"]),
        ("INFY", "Infosys Limited", "INE009A01021", ["INFY.NS", "INFY.BO"]),
        ("TATAMOTORS", "Tata Motors Limited", "INE155A01022", ["TATAMOTORS.BO", "TATAMOTORS.NS", "TMPV.NS"]),
        ("ITC", "ITC Limited", "INE154A01025", ["ITC.NS", "ITC.BO"]),
        ("ICICIBANK", "ICICI Bank Limited", "INE090A01021", ["ICICIBANK.NS", "ICICIBANK.BO"]),
        ("SBIN", "State Bank of India", "INE062A01020", ["SBIN.NS", "SBIN.BO"])
    ]
    for sym, name, isin, lookup_tickers in equities:
        records.append({
            "uid": f"STOCK_{sym}",
            "category": "STOCK",
            "name": name,
            "symbol_or_code": f"{sym}.NS",
            "lookup_tickers": lookup_tickers,
            "isin": isin,
            "issuer": "NSE India",
            "latest_nav": None,
            "nav_date": today_str
        })

    # 2. ETFs
    etfs = [
        ("NIFTYBEES", "Nippon India Nifty 50 BeES ETF", "INF204KB14I2", ["NIFTYBEES.NS", "NIFTYBEES.BO"]),
        ("BANKBEES", "Nippon India Nifty Bank BeES ETF", "INF204KB14L6", ["BANKBEES.NS", "BANKBEES.BO"]),
        ("GOLDBEES", "Nippon India ETF Gold BeES", "INF732E01037", ["GOLDBEES.NS", "GOLDBEES.BO"]),
        ("SILVERBEES", "Nippon India Silver ETF", "INF204KB19R0", ["SILVERBEES.NS", "SILVERBEES.BO"]),
        ("JUNIORBEES", "Nippon India Nifty Next 50 Junior BeES ETF", "INF204K01016", ["JUNIORBEES.NS", "JUNIORBEES.BO"])
    ]
    for sym, name, isin, lookup_tickers in etfs:
        records.append({
            "uid": f"ETF_{sym}",
            "category": "ETF",
            "name": name,
            "symbol_or_code": f"{sym}.NS",
            "lookup_tickers": lookup_tickers,
            "isin": isin,
            "issuer": "NSE India",
            "latest_nav": None,
            "nav_date": today_str
        })

    # 3. Sovereign Gold Bonds (With dual BSE/NSE debt symbol tickers)
    sgbs = [
        ("SGBMAY29", "Sovereign Gold Bond 2021-22 Series I", "IN0020210053", ["SGBMAY29.BO", "SGBMAY29-GB.NS", "SGBMAY29.NS"]),
        ("SGBDE28", "Sovereign Gold Bond 2020-21 Series IX", "IN0020200377", ["SGBDE28.BO", "SGBDE28-GB.NS", "SGBDE28.NS"]),
        ("SGBJA29", "Sovereign Gold Bond 2020-21 Series X", "IN0020200385", ["SGBJA29.BO", "SGBJA29-GB.NS", "SGBJA29.NS"]),
        ("SGBMR30", "Sovereign Gold Bond 2021-22 Series X", "IN0020210210", ["SGBMR30.BO", "SGBMR30-GB.NS", "SGBMR30.NS"])
    ]
    for sym, name, isin, lookup_tickers in sgbs:
        records.append({
            "uid": f"SGB_{sym}",
            "category": "SGB",
            "name": name,
            "symbol_or_code": f"{sym}.NS",
            "lookup_tickers": lookup_tickers,
            "isin": isin,
            "issuer": "Reserve Bank of India",
            "latest_nav": None,
            "nav_date": today_str
        })

    # 4. Resolve Live Prices
    for r in records:
        price = extract_price(r["lookup_tickers"])
        if price is not None and not math.isnan(price):
            r["latest_nav"] = price

    # 5. Database Upsert
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    for r in records:
        params = (
            r["uid"],
            r["category"],
            r["name"],
            r["symbol_or_code"],
            r.get("isin"),
            r["issuer"],
            r["latest_nav"],
            r["nav_date"],
            now_iso
        )
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
    print(f"[Markets] Completed upsert for {len(records)} instruments.")

if __name__ == "__main__":
    sync()
