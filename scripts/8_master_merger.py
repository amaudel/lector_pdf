import os
import json
import argparse
import sys
import sqlite3
from pathlib import Path
from datetime import datetime

class MasterMerger:
    def __init__(self, ready_file_str, master_db_str, output_dir_str, force_reprocess=False):
        self.ready_file = Path(ready_file_str).resolve()
        self.master_db = Path(master_db_str).resolve()
        self.output_dir = Path(output_dir_str).resolve()
        self.force_reprocess = force_reprocess
        
        if not self.ready_file.exists():
            print(f"ERROR: Archivo de entrada maestro no encontrado en {self.ready_file}")
            sys.exit(1)
            
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.master_db.parent.mkdir(parents=True, exist_ok=True)
        
        # Derivar lote
        filename = self.ready_file.name
        self.lote_base = filename.replace("ready_for_master_", "").replace(".jsonl", "")
        self.report_file = self.output_dir / f"master_merge_report_{self.lote_base}.json"
        
        self.metrics = {
            "total_registros_leidos": 0,
            "total_insertados": 0,
            "total_actualizados": 0,
            "total_rechazados": 0,
            "razones_de_rechazo": {}
        }
        
    def _rechazar(self, razon):
        self.metrics["total_rechazados"] += 1
        self.metrics["razones_de_rechazo"][razon] = self.metrics["razones_de_rechazo"].get(razon, 0) + 1

    def _init_db(self, cursor):
        # Tabla Principal de Entidades Maestras
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS master_entities (
                ruc TEXT PRIMARY KEY,
                razon_social_canonica TEXT NOT NULL,
                razon_social_normalizada TEXT NOT NULL,
                tipo_entidad TEXT,
                provincia_preferida TEXT,
                estado_resolucion_master TEXT,
                fuente_primaria TEXT,
                fecha_primera_aparicion TEXT,
                fecha_ultima_actualizacion TEXT,
                total_lotes_detectado INTEGER DEFAULT 1,
                total_menciones INTEGER DEFAULT 1
            )
        ''')
        
        # Tabla de Evidencia y Trazabilidad Granular
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS master_evidence (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ruc TEXT NOT NULL,
                lote TEXT NOT NULL,
                archivo_origen TEXT,
                pagina_pdf INTEGER,
                fragmento_evidencia TEXT,
                estado_resolucion_origen TEXT,
                fecha_ingesta TEXT,
                fuente_ruc TEXT,
                FOREIGN KEY (ruc) REFERENCES master_entities(ruc)
            )
        ''')
        
        # Tabla de Control de Lotes (Protección contra duplicación)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS processed_batches (
                lote_base TEXT PRIMARY KEY,
                fecha_procesamiento TEXT,
                total_registros_leidos INTEGER,
                total_insertados INTEGER,
                total_actualizados INTEGER,
                referencia_archivo TEXT
            )
        ''')
        
        # Índices de performance y blindaje
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_evidence_ruc ON master_evidence (ruc)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_evidence_lote ON master_evidence (lote)')
        
        # Índice Único que previene la inserción de la misma evidencia 2 veces accidentalmente
        cursor.execute('''
            CREATE UNIQUE INDEX IF NOT EXISTS idx_evidence_unique 
            ON master_evidence (ruc, lote, archivo_origen, fragmento_evidencia)
        ''')

    def _rollback_batch(self, cursor):
        print(f"\n[*] Ejecutando Rollback Transaccional del lote '{self.lote_base}'...")
        
        # 1. Cuantificar el impacto del lote previo para su reversión matemática
        # Usamos LIKE para aceptar lotes guardados con o sin ".zip" en el JSON original
        cursor.execute("SELECT ruc, COUNT(*) FROM master_evidence WHERE lote LIKE ? GROUP BY ruc", (self.lote_base + '%',))
        impactos = cursor.fetchall()  # Retorna lista de (ruc, cantidad_de_evidencias_en_este_lote)
        
        entidades_purgadas = 0
        metricas_revertidas = 0
        
        for ruc, menciones_q in impactos:
            if not ruc: continue
            
            # Restamos las menciones y le quitamos 1 a la cantidad de lotes que lo vieron
            cursor.execute('''
                UPDATE master_entities 
                SET total_menciones = total_menciones - ?,
                    total_lotes_detectado = total_lotes_detectado - 1
                WHERE ruc = ?
            ''', (menciones_q, ruc))
            metricas_revertidas += 1
            
            # Recolector de Basura (Si la entidad solo existió por este lote, desaparece)
            cursor.execute("DELETE FROM master_entities WHERE ruc = ? AND total_lotes_detectado <= 0", (ruc,))
            if cursor.rowcount > 0:
                entidades_purgadas += 1
                
        # 2. Borrar evidencias atómicas pasadas
        cursor.execute("DELETE FROM master_evidence WHERE lote LIKE ?", (self.lote_base + '%',))
        evidencias_borradas = cursor.rowcount
        
        # 3. Liberar el candado
        cursor.execute("DELETE FROM processed_batches WHERE lote_base = ?", (self.lote_base,))
        
        print(f" -> Rollback exitoso. {evidencias_borradas} evidencias destruidas.")
        print(f" -> {metricas_revertidas} métricas de RUC ajustadas ({entidades_purgadas} entidades maestras eliminadas por quedar huérfanas).")

    def merge(self):
        print(f"[*] Conectando al Repositorio Maestro: {self.master_db.name}")
        
        conn = sqlite3.connect(self.master_db)
        cursor = conn.cursor()
        
        try:
            self._init_db(cursor)
            
            # --- CONTROL DE IDEMPOTENCIA ---
            cursor.execute("SELECT fecha_procesamiento FROM processed_batches WHERE lote_base = ?", (self.lote_base,))
            batch_record = cursor.fetchone()
            
            if batch_record:
                if not self.force_reprocess:
                    print(f"\n[!] BLOQUEO DE SEGURIDAD: El lote '{self.lote_base}' ya fue integrado el {batch_record[0]}.")
                    print("    Continuar duplicaría artificialmente las menciones totales en master_entities.")
                    print("    Operación abortada. Si requiere correcciones, use --force_reprocess para purgar y reiniciar.")
                    sys.exit(0)
                else:
                    print(f"\n[!] ADVERTENCIA: Forzando reproceso. Se detectó historial previo.")
                    self._rollback_batch(cursor)
                    # Forzar un commit intermedio aquí protege la transacción de reversión
                    conn.commit()
            # -------------------------------
            
            ts_ahora = datetime.now().isoformat()
            
            with open(self.ready_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if not line.strip(): continue
                    
                    self.metrics["total_registros_leidos"] += 1
                    try:
                        cand = json.loads(line)
                    except json.JSONDecodeError:
                        self._rechazar("JSON Corrupto")
                        continue
                        
                    ruc = cand.get("ruc_final", "").strip()
                    
                    if not ruc or ruc.lower() in ["", "none", "null"]:
                        self._rechazar("Carece de RUC resolutivo absoluto")
                        continue
                        
                    cand_orig = cand.get("candidato_original", {})
                    rz_canonica = cand.get("razon_social_candidata") or cand_orig.get("razon_social_original", "DESCONOCIDA")
                    rz_norm = cand.get("razon_social_normalizada", "DESCONOCIDA")
                    tipo = cand_orig.get("tipo_entidad_detectada", "DESCONOCIDO")
                    prov = cand.get("coincidencia_provincia") or cand_orig.get("provincia_mencionada", "DESCONOCIDA")
                    estado_res = cand.get("estado_resolucion", "DESCONOCIDO")
                    fuente_ruc = cand.get("fuente_ruc", "DESCONOCIDO")
                    lote_nombre = cand.get("lote", self.lote_base)
                    menciones = cand_orig.get("menciones_totales", 1)
                    
                    # 1. UPSERT A MASTER_ENTITIES
                    cursor.execute("SELECT ruc, total_lotes_detectado, total_menciones FROM master_entities WHERE ruc = ?", (ruc,))
                    row = cursor.fetchone()
                    
                    if row:
                        cursor.execute('''
                            UPDATE master_entities SET
                                total_lotes_detectado = total_lotes_detectado + 1,
                                total_menciones = total_menciones + ?,
                                fecha_ultima_actualizacion = ?
                            WHERE ruc = ?
                        ''', (menciones, ts_ahora, ruc))
                        self.metrics["total_actualizados"] += 1
                    else:
                        cursor.execute('''
                            INSERT INTO master_entities (
                                ruc, razon_social_canonica, razon_social_normalizada, tipo_entidad,
                                provincia_preferida, estado_resolucion_master, fuente_primaria,
                                fecha_primera_aparicion, fecha_ultima_actualizacion,
                                total_lotes_detectado, total_menciones
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (
                            ruc, rz_canonica, rz_norm, tipo, prov, estado_res, fuente_ruc,
                            ts_ahora, ts_ahora, 1, menciones
                        ))
                        self.metrics["total_insertados"] += 1
                        
                    # 2. INSERTAR EVIDENCIA GRANULAR FÍSICA CON DEFENSA
                    archivos = cand_orig.get("archivos_origen", [])
                    paginas = cand_orig.get("paginas_origen", [])
                    fragmentos = cand_orig.get("fragmentos_evidencia", [])
                    
                    limit = max(len(archivos), len(paginas), len(fragmentos), 1)
                    for i in range(limit):
                        a = archivos[i] if i < len(archivos) else (archivos[-1] if archivos else "Desconocido")
                        p = paginas[i] if i < len(paginas) else (paginas[-1] if paginas else 0)
                        f = fragmentos[i] if i < len(fragmentos) else (fragmentos[-1] if fragmentos else "")
                        
                        try:
                            cursor.execute('''
                                INSERT INTO master_evidence (
                                    ruc, lote, archivo_origen, pagina_pdf, fragmento_evidencia,
                                    estado_resolucion_origen, fecha_ingesta, fuente_ruc
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            ''', (ruc, lote_nombre, a, int(p) if str(p).isdigit() else 0, str(f), estado_res, ts_ahora, fuente_ruc))
                        except sqlite3.IntegrityError:
                            # Ignorar duplicidad a nivel de fragmento atómico
                            pass
                        
            # Cierre Exitoso: Firmar Lote como procesado
            cursor.execute('''
                INSERT OR REPLACE INTO processed_batches 
                (lote_base, fecha_procesamiento, total_registros_leidos, total_insertados, total_actualizados, referencia_archivo)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (self.lote_base, ts_ahora, self.metrics["total_registros_leidos"], self.metrics["total_insertados"], self.metrics["total_actualizados"], str(self.ready_file.name)))
                        
            conn.commit()
            
        except sqlite3.Error as e:
            print(f"[!] Error de Motor SQLite integrando al repositorio maestro: {e}")
            conn.rollback()
            sys.exit(1)
            
        except Exception as e:
            print(f"[!] Error crítico integrando al repositorio maestro: {e}")
            conn.rollback()
            sys.exit(1)
            
        finally:
            cursor.close()
            conn.close()
            
        reporte = {
            "lote_mergeado": self.lote_base,
            "fecha_merge": datetime.now().isoformat(),
            "estadisticas_integracion": self.metrics,
            "base_maestra_ruta": str(self.master_db),
            "estado_idempotencia": "FORZADO" if self.force_reprocess else "NUEVO"
        }
        
        with open(self.report_file, 'w', encoding='utf-8') as f_rep:
            json.dump(reporte, f_rep, ensure_ascii=False, indent=2)

        print(f"=========================================")
        print(f" INTEGRACIÓN MAESTRA (PASO 8) ")
        print(f"=========================================")
        print(f" Lote Status    : {'REPROCESADO' if self.force_reprocess else 'VIRGEN'} ({self.lote_base})")
        print(f" Leídos Aptos   : {self.metrics['total_registros_leidos']}")
        print(f" -> Insertados  : {self.metrics['total_insertados']} (Nuevos RUCs globales)")
        print(f" -> Actualizado : {self.metrics['total_actualizados']} (Ampliados con más menciones)")
        print(f" -> Rechazados  : {self.metrics['total_rechazados']}")
        if self.metrics["razones_de_rechazo"]:
            for m, t in self.metrics["razones_de_rechazo"].items():
                print(f"     * {m}: {t}")
        print(f"=========================================")
        print(f"[*] Repositorio Central protegido en: {self.master_db.name}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Paso 8: Integra candidatos Aptos a la Master Database con seguridad idempotente.")
    parser.add_argument("--ready_path", required=True, help="Ruta de candidates habilitados (ready_for_master...)")
    parser.add_argument("--master_db", required=True, help="Ruta SQLite maestra transversal")
    parser.add_argument("--output_dir", required=True, help="Directorio para alojar el reporte del merge del lote")
    parser.add_argument("--force_reprocess", action="store_true", help="Salta el bloqueo de protección de lote duplicado")
    args = parser.parse_args()
    
    merger = MasterMerger(args.ready_path, args.master_db, args.output_dir, args.force_reprocess)
    merger.merge()
