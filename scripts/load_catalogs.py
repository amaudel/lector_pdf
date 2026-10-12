import sqlite3
import pandas as pd
import os
import glob
from pathlib import Path

# Configuración
OUTPUT_DB = "data/external/catalogs.sqlite"

def init_db():
    if os.path.exists(OUTPUT_DB):
        os.remove(OUTPUT_DB)
    
    conn = sqlite3.connect(OUTPUT_DB)
    # Tabla principal para búsqueda rápida
    conn.execute("""
        CREATE TABLE IF NOT EXISTS entities (
            ruc TEXT PRIMARY KEY,
            razon_social TEXT,
            provincia TEXT,
            tipo TEXT,
            fuente TEXT
        )
    """)
    # Tabla FTS5 para búsqueda por nombre (fuzzy match)
    conn.execute("""
        CREATE VIRTUAL TABLE entities_fts USING fts5(
            ruc UNINDEXED,
            razon_social,
            content='entities'
        )
    """)
    # Trigger para mantener FTS sincronizado
    conn.execute("""
        CREATE TRIGGER entities_ai AFTER INSERT ON entities BEGIN
            INSERT INTO entities_fts(ruc, razon_social) VALUES (new.ruc, new.razon_social);
        END;
    """)
    return conn

def load_seps_financiero(conn):
    print("[*] Cargando SEPS Financiero...")
    path = "data/external/catastro_seps_financiero.xlsx"
    if not os.path.exists(path): return
    
    # Header en fila 2 (0-indexed)
    df = pd.read_excel(path, header=2)
    # Columnas: 'Ruc', 'Razón Social', 'Provincia', 'Tipo'
    data = df[['Ruc', 'Razón Social', 'Provincia']].dropna(subset=['Ruc'])
    data.columns = ['ruc', 'razon_social', 'provincia']
    data['tipo'] = 'COOP'
    data['fuente'] = 'SEPS_FIN'
    
    data.to_sql('entities', conn, if_exists='append', index=False)
    conn.commit()
    print(f"  -> {len(data)} registros cargados.")

def load_seps_eps(conn):
    print("[*] Cargando SEPS EPS...")
    path = "data/external/catastro_seps_eps.xlsx"
    if not os.path.exists(path): return
    
    # Header en fila 3 (0-indexed)
    df = pd.read_excel(path, header=3)
    # Columnas: 'RUC', 'RAZON SOCIAL', 'PROVINCIA'
    data = df[['RUC', 'RAZON SOCIAL', 'PROVINCIA']].dropna(subset=['RUC'])
    data.columns = ['ruc', 'razon_social', 'provincia']
    data['tipo'] = 'ASOC' # La mayoría son asociaciones
    data['fuente'] = 'SEPS_EPS'
    
    # Evitar duplicados con el financiero por si acaso
    data.to_sql('entities', conn, if_exists='append', index=False, method=None)
    conn.commit()
    print(f"  -> {len(data)} registros cargados.")

def load_sri_csvs(conn):
    print("[*] Cargando SRI catastros (CSV)...")
    csv_files = glob.glob("data/external/SRI_RUC_*.csv") + glob.glob("data/external/sri_ruc_*.csv")
    
    cursor = conn.cursor()
    for csv_file in csv_files:
        print(f"  -> Procesando {os.path.basename(csv_file)}...")
        # Usar chunksize para no agotar RAM (estos CSVs son de 700MB)
        # Notas: 'ESTADO_CONTRIBUYENTE' puede ser util
        try:
            reader = pd.read_csv(csv_file, sep='|', chunksize=50000, 
                                 encoding='latin1', on_bad_lines='skip',
                                 usecols=['NUMERO_RUC', 'RAZON_SOCIAL', 'CODIGO_JURISDICCION'])
            
            count = 0
            for chunk in reader:
                chunk = chunk.dropna(subset=['NUMERO_RUC'])
                chunk['tipo'] = 'OTRO'
                chunk['fuente'] = 'SRI'
                
                # Mas rapido con executemany
                data_tpls = list(zip(chunk['NUMERO_RUC'], chunk['RAZON_SOCIAL'], 
                                   chunk['CODIGO_JURISDICCION'], chunk['tipo'], chunk['fuente']))
                
                cursor.executemany("INSERT OR IGNORE INTO entities VALUES (?,?,?,?,?)", data_tpls)
                count += len(chunk)
            
            conn.commit()
            print(f"  -> {count} registros leídos de {os.path.basename(csv_file)}.")
        except Exception as e:
            print(f"  [!] Error procesando {csv_file}: {e}")

if __name__ == "__main__":
    conn = init_db()
    load_seps_financiero(conn)
    load_seps_eps(conn)
    
    # Importante: SRI tiene muchos registros duplicados o de personas naturales.
    # En esta versión simplificada cargamos los catastros de provincias clave.
    load_sri_csvs(conn)
    
    print("\n[*] Optimizando base de datos...")
    conn.execute("ANALYZE")
    conn.execute("VACUUM")
    conn.close()
    print("[!] Catálogo cargado exitosamente en catalogs.sqlite")
