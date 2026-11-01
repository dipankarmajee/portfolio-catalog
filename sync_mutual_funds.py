import os
import sqlite3
from datetime import datetime
import requests

DB_PATH = os.path.join("data", "master_mutual_funds.sqlite")
os.makedirs("data", exist_ok=True)
HEADERS = {"User-Agent": "Mozilla/5.0"}

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS mutual_funds (
            uid TEXT PRIMARY KEY,
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
    print("[Mutual Funds] Fetching AMFI NAV feed...")
    url = "https://www.amfiindia.com/spages/NAVAll.txt"
    resp = requests.get(url, headers=HEADERS, timeout=30)
    
    records = []
    for line in resp.text.splitlines():
        line = line.strip()
        if not line or ";" not in line or line.startswith("Scheme Code"):
            continue
        cols = [c.strip() for c in line.split(";")]
        if len(cols) >= 5:
            code = cols[0]
            if not code.isdigit():
                continue
            date_val = cols[-1]
            raw_nav = cols[-2]
            name = cols[3] if len(cols) == 6 else " ".join(cols[3:-2])
            try:
                nav = float(raw_nav)
            except ValueError:
                nav = None
                
            records.append((f"MF_{code}", name, code, "AMFI Registered AMC", nav, date_val))

    if not records:
        print("[Mutual Funds] No records found, skipping write.")
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    now_iso = datetime.now().isoformat()
    fetched_uids = set()

    for r in records:
        fetched_uids.add(r[0])
        params = (r[0], r[1], r[2], r[3], r[4], r[5], now_iso)
        cur.execute("""
            INSERT INTO mutual_funds (uid, name, symbol_or_code, issuer, latest_nav, nav_date, status, last_synced_at)
            VALUES (?, ?, ?, ?, ?, ?, 'ACTIVE', ?)
            ON CONFLICT(uid) DO UPDATE SET
                name=excluded.name,
                latest_nav=excluded.latest_nav,
                nav_date=excluded.nav_date,
                status='ACTIVE',
                last_synced_at=excluded.last_synced_at
        """, params)

    # Soft-delete: mark unlisted/removed schemes as DEACTIVATED
    cur.execute("SELECT uid FROM mutual_funds WHERE status = 'ACTIVE'")
    active_uids = {row[0] for row in cur.fetchall()}
    missing = active_uids - fetched_uids
    if missing:
        cur.executemany(
            "UPDATE mutual_funds SET status = 'DEACTIVATED', last_synced_at = ? WHERE uid = ?",
            [(now_iso, uid) for uid in missing]
        )
        print(f"[Mutual Funds] Deactivated {len(missing)} inactive schemes.")

    conn.commit()
    conn.close()
    print(f"[Mutual Funds] Ingested {len(records)} records successfully.")

if __name__ == "__main__":
    sync()
