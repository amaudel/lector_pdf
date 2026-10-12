import sqlite3
import sys
db_path = "data/external/catalogs.sqlite"
try:
    conn = sqlite3.connect(db_path)
    with open('db_schema.txt', 'w', encoding='utf-8') as f:
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        for table in tables:
            tname = table[0]
            f.write(f"TABLE: {tname}\n")
            cols = conn.execute(f"PRAGMA table_info({tname})").fetchall()
            for col in cols:
                f.write(f"  {col}\n")
    print("Schema written to db_schema.txt")
except Exception as e:
    print(str(e))
