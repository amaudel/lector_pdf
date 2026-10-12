import sqlite3
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

db_path = Path("c:/Users/User/Documents/LECTOR PDF/data/master/master_entities.sqlite")

if not db_path.exists():
    print("La base de datos maestra no existe.")
    sys.exit(0)

print(f"Conectando a {db_path}...")
conn = sqlite3.connect(db_path)
c = conn.cursor()

try:
    # Definir filtros SQL para placeholders y entidades basura
    placeholders = [
        "NONE", "NULL", "NOME", "UNKNOWN", "DESCONOCIDA", "DESCONOCIDO", "SIN DATO", "SIN_DATO", "NO DISPONIBLE"
    ]
    
    # Construir condición SQL
    conditions = []
    for p in placeholders:
        conditions.append(f"razon_social_normalizada = '{p}'")
        conditions.append(f"razon_social_normalizada LIKE '{p} %'")
    
    # También añadir longitud menor a 3
    conditions.append("length(razon_social_normalizada) < 3")
    
    query_condition = " OR ".join(conditions)
    
    # Contar
    c.execute(f"SELECT ruc, razon_social_canonica FROM master_entities WHERE {query_condition}")
    all_rows = c.fetchall()
    
    if not all_rows:
        print("No se encontraron entidades basura (NULL, NOME, placeholders) en master_entities.")
        sys.exit(0)
        
    print(f"Encontradas {len(all_rows)} entidades basura para eliminar:")
    for r in all_rows:
        print(f"  RUC: {r[0]} | Nombre: {r[1]}")
        
    # Borrar evidencias asociadas
    c.execute(f"""
        DELETE FROM master_evidence 
        WHERE ruc IN (SELECT ruc FROM master_entities WHERE {query_condition})
    """)
    print(f"Eliminadas {c.rowcount} evidencias asociadas de master_evidence.")
    
    # Borrar entidades de master_entities
    c.execute(f"DELETE FROM master_entities WHERE {query_condition}")
    print(f"Eliminadas {c.rowcount} entidades de master_entities.")
    
    conn.commit()
    print("[*] Saneamiento completado exitosamente.")
    
except Exception as e:
    print(f"Error: {e}")
    conn.rollback()
finally:
    conn.close()
