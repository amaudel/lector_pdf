import sqlite3
import sys
from pathlib import Path

# Configurar encoding para consola
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

db_path = Path("c:/Users/User/Documents/LECTOR PDF/data/master/master_entities.sqlite")

if not db_path.exists():
    print(f"La base de datos maestra no existe en {db_path}")
    sys.exit(0)

print(f"Conectando a {db_path}...")
conn = sqlite3.connect(db_path)
c = conn.cursor()

try:
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='master_entities'")
    if not c.fetchone():
        print("La tabla master_entities no existe.")
        sys.exit(0)

    # 1. Contar registros con RUC inválido (longitud distinta a 13)
    c.execute("SELECT COUNT(*) FROM master_entities WHERE length(ruc) != 13")
    count_entities = c.fetchone()[0]
    
    if count_entities == 0:
        print("No se encontraron entidades con RUCs inválidos (longitud != 13) en master_entities.")
        sys.exit(0)

    print(f"Encontrados {count_entities} registros con RUC inválido en master_entities.")

    # 2. Borrar evidencias asociadas
    c.execute("""
        DELETE FROM master_evidence 
        WHERE ruc IN (SELECT ruc FROM master_entities WHERE length(ruc) != 13)
    """)
    count_evidence = cursor_count = c.rowcount
    print(f"Eliminadas {count_evidence} evidencias asociadas de master_evidence.")

    # 3. Borrar entidades de master_entities
    c.execute("DELETE FROM master_entities WHERE length(ruc) != 13")
    print(f"Eliminadas {c.rowcount} entidades de master_entities.")

    # 4. Confirmar transacción
    conn.commit()
    print("[*] Base de datos maestra limpiada y saneada exitosamente.")

except Exception as e:
    print(f"Error: {e}")
    conn.rollback()
finally:
    conn.close()
