import sqlite3
import csv
import sys
import argparse
from pathlib import Path
from datetime import datetime
import re

def normalize_business_name(name):
    if not name: return ""
    n = name.upper()
    n = re.sub(r'[\"\'\“\”\.,;]', '', n)
    n = re.sub(r'\s+', ' ', n)
    return n.strip()

def ingest_csv_to_sqlite(csv_path_str, db_path_str, source_name="SRI_OPEN_DATA"):
    csv_path = Path(csv_path_str).resolve()
    db_path = Path(db_path_str).resolve()
    
    if not csv_path.exists():
        print(f"ERROR: Archivo CSV no encontrado en {csv_path}")
        sys.exit(1)
        
    print(f"[*] Conectando a SQLite en {db_path}...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Crear esquema recomendado
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS padron_empresas (
            ruc TEXT PRIMARY KEY,
            razon_social TEXT NOT NULL,
            razon_social_normalizada TEXT NOT NULL,
            provincia TEXT,
            estado TEXT,
            fuente_dataset TEXT,
            fecha_dataset TEXT
        )
    ''')
    
    # Índices críticos para performance
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_padron_rsn ON padron_empresas (razon_social_normalizada)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_padron_provincia ON padron_empresas (provincia)')
    
    print(f"[*] Ingiriendo datos desde {csv_path.name}...")
    
    bulk_data = []
    fecha_actual = datetime.now().strftime("%Y-%m-%d")
    
    # Procesar chunk por chunk
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            
            # Mapeo flexible de headers
            # Idealmente el CSV debe tener RUC, RAZON_SOCIAL, PROVINCIA, ESTADO
            headers = [h.upper() for h in reader.fieldnames]
            
            col_ruc = next((h for h in headers if "RUC" in h), "RUC")
            col_rs = next((h for h in headers if "SOCIAL" in h or "NOMBRE" in h), "RAZON_SOCIAL")
            col_prov = next((h for h in headers if "PROVINCIA" in h), "PROVINCIA")
            col_estado = next((h for h in headers if "ESTADO" in h), "ESTADO")
            
            for row_dict in reader:
                # Normalizar keys ignorando case
                row = {k.upper(): v for k, v in row_dict.items()}
                
                ruc = row.get(col_ruc, "").strip()
                rz = row.get(col_rs, "").strip()
                prov = row.get(col_prov, "").strip()
                estado = row.get(col_estado, "ACTIVO").strip()
                
                if not ruc or not rz: continue
                
                rz_norm = normalize_business_name(rz)
                
                bulk_data.append((ruc, rz, rz_norm, prov, estado, source_name, fecha_actual))
                
                # Ejecutar lote cada 50,000 registros para no saturar memoria
                if len(bulk_data) >= 50000:
                    cursor.executemany('''
                        INSERT OR REPLACE INTO padron_empresas 
                        (ruc, razon_social, razon_social_normalizada, provincia, estado, fuente_dataset, fecha_dataset)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', bulk_data)
                    conn.commit()
                    print(f" -> Insertados {len(bulk_data)} registros...")
                    bulk_data = []
                    
        # Insertar el remanente
        if bulk_data:
            cursor.executemany('''
                INSERT OR REPLACE INTO padron_empresas 
                (ruc, razon_social, razon_social_normalizada, provincia, estado, fuente_dataset, fecha_dataset)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', bulk_data)
            conn.commit()
            print(f" -> Insertados {len(bulk_data)} registros finales.")
            
    except Exception as e:
        print(f"[!] Error crítico durante ingesta: {e}")
        conn.rollback()
        sys.exit(1)
        
    finally:
        cursor.close()
        conn.close()
        
    print(f"[*] Ingesta completada con éxito. Base optimizada y lista.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingesta masiva de CSV a SQLite para DatasetAdapter.")
    parser.add_argument("--csv_path", required=True, help="Ruta al CSV bruto del SRI.")
    parser.add_argument("--db_path", required=True, help="Ruta de destino del archivo SQLite.")
    parser.add_argument("--source", default="SRI_PADRON_ABIERTO", help="Nombre descriptivo de la fuente para auditoría.")
    args = parser.parse_args()
    
    ingest_csv_to_sqlite(args.csv_path, args.db_path, args.source)
