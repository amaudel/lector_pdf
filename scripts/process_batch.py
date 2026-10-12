import os
import sys
import json
import argparse
import subprocess
from pathlib import Path
from datetime import datetime

class BatchOrchestrator:
    def __init__(self, zip_path, master_db, output_dir, args):
        self.zip_path = Path(zip_path).resolve()
        self.master_db = Path(master_db).resolve()
        self.output_dir = Path(output_dir).resolve()
        self.args = args
        
        self.lote_base = self.zip_path.name
        if self.lote_base.endswith('.zip'):
            self.lote_base = self.lote_base[:-4]
            
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.report_file = self.output_dir / f"pipeline_run_report_{self.lote_base}.json"
        
        self.paths = {
            "inventory": Path("data/temp").resolve() / self.lote_base / "inventory.json",
            "consolidated": self.output_dir / f"consolidated_{self.lote_base}.jsonl",
            "extracted": self.output_dir / f"entities_extracted_{self.lote_base}.jsonl",
            "candidates": self.output_dir / f"candidates_{self.lote_base}.jsonl",
            "resolved": self.output_dir / f"resolved_{self.lote_base}.jsonl",
            "ready": self.output_dir / f"ready_for_master_{self.lote_base}.jsonl",
            "manual_review": self.output_dir / f"manual_review_{self.lote_base}.jsonl",
            "not_ready": self.output_dir / f"not_ready_for_master_{self.lote_base}.jsonl",
            "web_enriched": self.output_dir / f"web_enriched_{self.lote_base}.jsonl"
        }
        
        # Diccionario enriquecido con prerrequisitos duros de input 
        self.steps = [
            {
                "id": "1", "name": "Unzip & Inventory", 
                "reqs": [self.zip_path],
                "cmd": ["python", "scripts/1_unzip_and_inventory.py", "--zip_path", str(self.zip_path), "--temp_dir", str(Path("data/temp").resolve())]
            },
            {
                "id": "2", "name": "Text Extraction (PyMuPDF)", 
                "reqs": [self.paths["inventory"]],
                "cmd": ["python", "scripts/2_extract_text.py", "--inventory_path", str(self.paths["inventory"])]
            },
            {
                "id": "3", "name": "Batch Consolidation", 
                "reqs": [self.paths["inventory"]], # Técnicamente depende de carpetas tx_... pero el inventory prueba completitud
                "cmd": ["python", "scripts/3_consolidate_batch.py", "--inventory_path", str(self.paths["inventory"]), "--output_dir", str(self.output_dir)]
            },
            {
                "id": "4", "name": "Semantic Entity Extraction (LLM)", 
                "reqs": [self.paths["consolidated"]],
                "cmd": ["python", "scripts/4_extract_entities.py", "--consolidated_path", str(self.paths["consolidated"]), "--output_dir", str(self.output_dir)]
            },
            {
                "id": "5", "name": "Deduplication & Grouping", 
                "reqs": [self.paths["extracted"]],
                "cmd": ["python", "scripts/5_deduplicate_entities.py", "--entities_path", str(self.paths["extracted"]), "--output_dir", str(self.output_dir)]
            },
            {
                "id": "7", "name": "Candidates Resolution Engine", 
                "reqs": [self.paths["candidates"]],
                "cmd": ["python", "scripts/7_resolve_candidates.py", "--candidates_path", str(self.paths["candidates"]), "--output_dir", str(self.output_dir)]
            },
            {
                "id": "7.5", "name": "Quality Audit & Quarantine", 
                "reqs": [self.paths["resolved"]],
                "cmd": ["python", "scripts/7_5_evaluate_resolution.py", "--resolved_path", str(self.paths["resolved"]), "--output_dir", str(self.output_dir)]
            },
            {
                "id": "7B", "name": "Web Enrichment Layer (Opcional)",
                "reqs": [self.paths["manual_review"], self.paths["not_ready"]],
                "optional": True,
                "soft_fail": True,
                "cmd": ["python", "scripts/7B_web_enrichment.py", "--input_paths",
                        str(self.paths["manual_review"]), str(self.paths["not_ready"]),
                        "--output_dir", str(self.output_dir), "--mode", "REAL"]
            },
            {
                "id": "7.5B", "name": "Web Enrichment Quality Gate (Opcional)",
                "reqs": [self.paths["web_enriched"]],
                "optional": True,
                "soft_fail": True,
                "cmd": ["python", "scripts/7_5B_evaluate_web_enrichment.py",
                        "--enriched_path", str(self.paths["web_enriched"]),
                        "--output_dir", str(self.output_dir)]
            },
            {
                "id": "8", "name": "Master DB Integration", 
                "reqs": [self.paths["ready"]],
                "cmd": ["python", "scripts/8_master_merger.py", "--ready_path", str(self.paths["ready"]), "--master_db", str(self.master_db), "--output_dir", str(self.output_dir)]
            },
            {
                "id": "9", "name": "Analytic Export (Excel/JSON)", 
                "reqs": [self.paths["resolved"]],
                "soft_fail": True,
                "cmd": ["python", "scripts/9_export_business_results.py", "--resolved_path", str(self.paths["resolved"]), "--output_dir", str(self.output_dir), "--mode", "batch"]
            }
        ]
        
        if self.args.force_reprocess_master:
            for step in self.steps:
                if step["id"] == "8":
                    step["cmd"].append("--force_reprocess")
                    break
            
        self.status_log = {step["id"]: "NO_EJECUTADO" for step in self.steps}
        self.metrics = {"start_time": datetime.now().isoformat(), "end_time": None, "total_errors": 0}
        self.web_enrichment_enabled = getattr(self.args, 'enable_web_enrichment', False)

    def _should_schedule_step(self, step):
        step_id = step["id"]
        
        # Pasos opcionales requieren flag explícito
        if step.get("optional", False) and not self.web_enrichment_enabled:
            return False, "OMITIDO_WEB_NO_ACTIVADO"
        
        if self.args.skip_steps and step_id in self.args.skip_steps:
            return False, "OMITIDO_POR_SKIP"
            
        if self.args.resume_from_step:
            idx_current = next(i for i, s in enumerate(self.steps) if s["id"] == step_id)
            idx_resume = next((i for i, s in enumerate(self.steps) if s["id"] == self.args.resume_from_step), -1)
            if idx_resume != -1 and idx_current < idx_resume:
                return False, "OMITIDO_POR_RESUME"
                
        return True, ""

    def run(self):
        print(f"==================================================")
        print(f" PDF BATCH ORCHESTRATOR ETL - LOTE: {self.lote_base}")
        print(f"==================================================")
        print(f" -> ZIP Path : {self.zip_path.name}")
        print(f" -> Master DB: {self.master_db.name}")
        print(f" -> Dry Run  : {self.args.dry_run}")
        print(f" -> Web Enrich: {self.web_enrichment_enabled}")
        print(f"==================================================")
        
        is_first_scheduled_step = True
        
        for step in self.steps:
            sid = step["id"]
            name = step["name"]
            
            # Decidir agenda
            should_run, skip_reason = self._should_schedule_step(step)
            
            if not should_run:
                self.status_log[sid] = skip_reason
                print(f"[-] Paso {sid.ljust(4)} ({name}) -> {self.status_log[sid]}")
                continue
                
            print(f"\n[*] Preparando Paso {sid} ({name})...")
            
            # Validación dura de prerequisitos físicos
            missing_reqs = [r.name for r in step["reqs"] if not r.exists()]
            if missing_reqs:
                if not self.args.dry_run or is_first_scheduled_step:
                    reason = f"Faltan dependencias esperadas en disco: {', '.join(missing_reqs)}"
                    self.status_log[sid] = "ERROR_PRERREQUISITO"
                    self.metrics["total_errors"] += 1
                    print(f"[X] Fallo de Precondición: {reason}")
                    
                    if self.args.stop_on_error:
                        print("    -> Abortando pipeline secuencial para evitar catástrofe.")
                        break
                    continue
                else:
                    print(f"    [!] Aviso DRY RUN: Asumiendo existencia virtual de {', '.join(missing_reqs)} por herencia de la simulación previa.")
            
            # Desmarcamos el flag tras pasar validación del eslabón base de la cadena reanudada
            is_first_scheduled_step = False 

            cmd_str = " ".join(step["cmd"])
            
            # Rama de Simulación
            if self.args.dry_run:
                print(f"    [SIMULANDO] Comando: {cmd_str}")
                self.status_log[sid] = "SIMULADO"
                continue
                
            # Rama de Ejecución Física Real
            try:
                result = subprocess.run(
                    step["cmd"], 
                    check=True, 
                    stdout=sys.stdout,
                    stderr=sys.stderr,
                    text=True
                )
                self.status_log[sid] = "OK"
                
            except subprocess.CalledProcessError as e:
                is_soft = step.get("soft_fail", False)
                self.status_log[sid] = f"ERROR_ESPERADO (Exit={e.returncode})" if is_soft else f"ERROR_EJECUCION (Exit={e.returncode})"
                
                if not is_soft: self.metrics["total_errors"] += 1
                
                print(f"\n[X] FALLO DE SUBPROCESO EN PASO {sid}. Cerró con status code {e.returncode}")
                
                if self.args.stop_on_error and not is_soft:
                    print("    -> Pipeline abortado por directiva stop_on_error.")
                    break
                elif is_soft:
                    print("    -> [!] Error en paso no crítico. El bloque principal se salvó. Continuando...")
                    
        self._finish_run()
        
    def _finish_run(self):
        self.metrics["end_time"] = datetime.now().isoformat()
        
        report = {
            "orchestrator_version": "1.1.0",
            "lote_procesado": self.lote_base,
            "web_enrichment_enabled": self.web_enrichment_enabled,
            "argumentos_ejecucion": vars(self.args),
            "estado_final_pasos": self.status_log,
            "metricas_tiempo": self.metrics,
            "dependencias_reconocidas": {k: str(v) for k, v in self.paths.items()}
        }
        
        with open(self.report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
            
        print("\n==================================================")
        print(f" REPORTE FINAL DE CASCADA. Errores Detectados: {self.metrics['total_errors']}")
        print(f"==================================================")
        for sid, st in self.status_log.items():
            print(f"    Paso {sid.ljust(4)} : {st}")
        print(f"==================================================")
        print(f"[*] Audit Log alojado en: {self.report_file.name}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Orquestador Maestro del Pipeline ETL para PDFs (Auditable).")
    
    parser.add_argument("--zip_path", required=True, help="Ruta del archivo ZIP contenedor de PDFs")
    parser.add_argument("--master_db", required=True, help="Ruta de la base de datos Sqlite Maestra")
    parser.add_argument("--output_dir", required=True, help="Directorio central donde alojar derivados")
    
    parser.add_argument("--dry_run", action="store_true", help="Simula en consola sin ejecución (Status: SIMULADO).")
    parser.add_argument("--no_stop_on_error", dest="stop_on_error", action="store_false", help="Desactiva detención por fallos.")
    parser.add_argument("--resume_from_step", type=str, help="Obliga a comenzar desde un ID de paso (ej. '4'). Valida dependencias de inmediato.")
    parser.add_argument("--skip_steps", type=str, nargs="+", help="Pasos específicos a excluir manualmente.")
    parser.add_argument("--force_reprocess_master", action="store_true", help="Permite revertir y re-ingestar lote si ya existía en DB Maestra.")
    parser.add_argument("--enable_web_enrichment", action="store_true", help="Activa los pasos opcionales 7B y 7.5B de enriquecimiento web (no alimenta al maestro).")
    
    
    parser.set_defaults(stop_on_error=True)
    args = parser.parse_args()
    
    orchestrator = BatchOrchestrator(args.zip_path, args.master_db, args.output_dir, args)
    orchestrator.run()
