import os
import sqlite3
from datetime import datetime
import requests
from bs4 import BeautifulSoup

DB_PATH = os.path.join("data", "master_insurers_ulips.sqlite")
os.makedirs("data", exist_ok=True)
HEADERS = {"User-Agent": "Mozilla/5.0"}

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS insurers (
            uid TEXT PRIMARY KEY,
            category TEXT NOT NULL,
            name TEXT NOT NULL,
            symbol_or_code TEXT NOT NULL,
            issuer TEXT,
            status TEXT NOT NULL,
            last_synced_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

def sync():
    init_db()
    print("[Insurers] Scraping Life Insurance Council directory...")
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
                    records.append((f"INSURER_{val}", "INSURER", text_name, val, "IRDAI"))
    except Exception as e:
        print(f"Scraper error: {e}")
        return

    if not records:
        print("[Insurers] No records fetched, skipping write.")
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    now_iso = datetime.now().isoformat()
    fetched_uids = set()

    for r in records:
        fetched_uids.add(r[0])
        params = (r[0], r[1], r[2], r[3], r[4], now_iso)
        cur.execute("""
            INSERT INTO insurers (uid, category, name, symbol_or_code, issuer, status, last_synced_at)
            VALUES (?, ?, ?, ?, ?, 'ACTIVE', ?)
            ON CONFLICT(uid) DO UPDATE SET
                name=excluded.name,
                status='ACTIVE',
                last_synced_at=excluded.last_synced_at
        """, params)

    conn.commit()
    conn.close()
    print(f"[Insurers] Upserted {len(records)} insurers.")

if __name__ == "__main__":
    sync()
