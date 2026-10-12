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
    # Definir filtros SQL para identificar registros a eliminar
    # 1. Que la razon_social_normalizada sea exactamente 'NONE' o empiece con 'NONE '
    # 2. Que contenga 'MASIVA'
    # 3. Que empiece con 'SCVS' o contenga 'S.C.V.S'
    
    query_condition = """
        razon_social_normalizada = 'NONE' 
        OR razon_social_normalizada LIKE 'NONE %' 
        OR razon_social_normalizada LIKE '%MASIVA%' 
        OR razon_social_normalizada LIKE 'SCVS%'
        OR razon_social_normalizada LIKE '%S.C.V.S%'
        OR razon_social_normalizada LIKE '%REGISTRO MERCANTIL%'
        OR razon_social_normalizada LIKE '%SERVICIO NACIONAL DE CONTRATACION%'
        OR razon_social_normalizada LIKE '%SERCOP%'
    """
    
    # Contar
    c.execute(f"SELECT COUNT(*), ruc, razon_social_canonica FROM master_entities WHERE {query_condition}")
    rows_to_delete = c.fetchall()
    
    c.execute(f"SELECT ruc, razon_social_canonica FROM master_entities WHERE {query_condition}")
    all_rows = c.fetchall()
    
    if not all_rows:
        print("No se encontraron entidades basura (NONE, MASIVA, SCVS) en master_entities.")
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
    print("[*] Saneamiento de entidades basura en base de datos maestra completado.")
    
except Exception as e:
    print(f"Error: {e}")
    conn.rollback()
finally:
    conn.close()
