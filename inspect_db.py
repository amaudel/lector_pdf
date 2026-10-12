import sqlite3
from pathlib import Path

db = Path("data/external/catalogs.sqlite")
conn = sqlite3.connect(db)
c = conn.cursor()

# Ver todas las tablas
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
print("=== TABLAS ===")
for t in c.fetchall():
    print(" -", t[0])
    # Ver columnas de cada tabla
    c2 = conn.cursor()
    c2.execute(f"PRAGMA table_info({t[0]})")
    cols = c2.fetchall()
    for col in cols:
        print(f"     [{col[1]}] tipo={col[2]}")
    # Ver 2 filas de muestra
    c2.execute(f"SELECT * FROM {t[0]} LIMIT 2")
    rows = c2.fetchall()
    for row in rows:
        print(f"     muestra: {row}")
    print()

conn.close()
