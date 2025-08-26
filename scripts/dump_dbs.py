"""Dump schema and all rows for every .db file under the repo root.
Run: python scripts/dump_dbs.py
"""

from pathlib import Path
import sqlite3
import json

root = Path(__file__).resolve().parents[1]
# Prefer the consolidated DB if present, otherwise fall back to scanning for .db files
preferred = root / "TwitchBuddy.db"
if preferred.exists():
    dbs = [preferred]
else:
    dbs = list(root.glob("**/*.db"))
    if not dbs:
        print("No .db files found under", root)
        raise SystemExit(0)

for db in dbs:
    print("\n===== DB:", db)
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    tables = [
        r[0]
        for r in cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    ]
    if not tables:
        print("  (no tables)")
        conn.close()
        continue
    print("Tables:", tables)
    print("\nSchema:")
    for row in cur.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall():
        print("\n--", row[0])
        print(row[1])
    print("\nContents:")
    for t in tables:
        print("\n-- TABLE:", t)
        cols = [c[0] for c in cur.execute(f"PRAGMA table_info({t})").fetchall()]
        print("Columns:", cols)
        rows = cur.execute(f"SELECT * FROM {t}").fetchall()
        if not rows:
            print("  (no rows)")
            continue
        for r in rows:
            # ensure values are JSON serializable
            d = {
                k: (v if isinstance(v, (int, float, str, type(None))) else str(v))
                for k, v in dict(r).items()
            }
            print(" ", json.dumps(d, ensure_ascii=False))
    conn.close()
