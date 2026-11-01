import os
import sqlite3
from datetime import datetime
import yfinance as yf

DB_PATH = os.path.join("data", "master_equities_etfs.sqlite")
os.makedirs("data", exist_ok=True)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS market_instruments (
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

def sync():
    init_db()
    print("[Markets] Fetching Equities, ETFs, and SGBs...")
    equities = ["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "TATAMOTORS.NS", "ITC.NS", "ICICIBANK.NS", "SBIN.NS"]
    etfs = ["NIFTYBEES.NS", "BANKBEES.NS", "GOLDBEES.NS", "SILVERBEES.NS", "JUNIORBEES.NS"]
    sgbs = ["SGBMAY29.NS", "SGBDE28.NS", "SGBJA29.NS", "SGBMR30.NS"]
    
    all_symbols = equities + etfs + sgbs
    records = []

    try:
        df = yf.download(all_symbols, period="5d", interval="1d", progress=False)
        close_df = df["Close"]

        for sym in all_symbols:
            try:
                if sym not in close_df.columns:
                    continue
                series = close_df[sym].dropna()
                if series.empty:
                    continue
                price = float(series.iloc[-1])

                if sym in equities:
                    category = "STOCK"
                    issuer = "NSE India"
                elif sym in etfs:
                    category = "ETF"
                    issuer = "NSE India"
                else:
                    category = "SGB"
                    issuer = "Reserve Bank of India"

                clean_sym = sym.replace(".NS", "")
                records.append({
                    "uid": f"{category}_{clean_sym}",
                    "category": category,
                    "name": sym,
                    "symbol_or_code": sym,
                    "issuer": issuer,
                    "latest_nav": round(price, 2),
                    "nav_date": datetime.now().strftime("%d-%b-%Y")
                })
            except Exception as e:
                print(f"Error parsing symbol {sym}: {e}")
    except Exception as e:
        print(f"Market batch download error: {e}")
        return

    if not records:
        print("[Markets] No records processed, skipping database write.")
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    now_iso = datetime.now().isoformat()
    fetched_uids = set()

    for r in records:
        fetched_uids.add(r["uid"])
        params = (r["uid"], r["category"], r["name"], r["symbol_or_code"], r["issuer"], r["latest_nav"], r["nav_date"], now_iso)
        cur.execute("""
            INSERT INTO market_instruments (uid, category, name, symbol_or_code, issuer, latest_nav, nav_date, status, last_synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?)
            ON CONFLICT(uid) DO UPDATE SET
                name=excluded.name,
                latest_nav=excluded.latest_nav,
                nav_date=excluded.nav_date,
                status='ACTIVE',
                last_synced_at=excluded.last_synced_at
        """, params)

    cur.execute("SELECT uid FROM market_instruments WHERE status = 'ACTIVE'")
    active_uids = {row[0] for row in cur.fetchall()}
    missing = active_uids - fetched_uids
    if missing:
        cur.executemany(
            "UPDATE market_instruments SET status = 'DEACTIVATED', last_synced_at = ? WHERE uid = ?",
            [(now_iso, uid) for uid in missing]
        )
        print(f"[Markets] Deactivated {len(missing)} missing instruments.")

    conn.commit()
    conn.close()
    print(f"[Markets] Upserted {len(records)} market records.")

if __name__ == "__main__":
    sync()
