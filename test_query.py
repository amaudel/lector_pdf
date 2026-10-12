import sqlite3

conn = sqlite3.connect('data/external/catalogs.sqlite')
c = conn.cursor()
c.execute("SELECT * FROM entities WHERE razon_social LIKE '%KORBAN%'")
res = c.fetchall()
for r in res:
    print(r)

if not res:
    print("NO SE ENCONTRO KORBAN")

c.execute("SELECT COUNT(*) FROM entities")
print("Total entidades:", c.fetchone()[0])
