import os
import json
import argparse
import sys
from pathlib import Path
from datetime import datetime

class ResolutionEvaluator:
    def __init__(self, resolved_path_str, manual_review_path_str, output_dir_str):
        self.resolved_path = Path(resolved_path_str).resolve()
        self.manual_review_path = Path(manual_review_path_str).resolve()
        self.output_dir = Path(output_dir_str).resolve()
        
        if not self.resolved_path.exists():
            print(f"ERROR: Archivo resolved no encontrado en {self.resolved_path}")
            sys.exit(1)
            
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Derivar lote
        filename = self.resolved_path.name
        self.lote_base = filename.replace("resolved_", "").replace(".jsonl", "")
        
        # Archivos de salida
        self.ready_file = self.output_dir / f"ready_for_master_{self.lote_base}.jsonl"
        self.not_ready_file = self.output_dir / f"not_ready_for_master_{self.lote_base}.jsonl"
        self.report_file = self.output_dir / f"resolution_audit_report_{self.lote_base}.json"
        
        # Reglas de negocio (Filtros de Madurez)
        self.aptos_conditions = [
            "RUC_EXTRAIDO_DEL_PDF",
            "COINCIDENCIA_DATASET_LOCAL_ALTA",
            "VALIDADO_DATASET_OFICIAL",
            "VALIDADO_EXTERNAMENTE"
        ]

    def evaluate(self):
        print(f"[*] Iniciando Auditoría y Evaluación de Calidad (Lote: {self.lote_base})")
        
        ready_list = []
        not_ready_list = []
        
        # Metricas
        metrics = {
            "total_evaluados": 0,
            "total_revisados_manual": 0,
            "aptos_para_maestro": 0,
            "no_aptos_para_maestro": 0,
            "desglose_estados": {}
        }
        
        def process_candidate(cand_dict):
            metrics["total_evaluados"] += 1
            estado = cand_dict.get("estado_resolucion", "DESCONOCIDO")
            
            # Registrar al desglose
            metrics["desglose_estados"][estado] = metrics["desglose_estados"].get(estado, 0) + 1
            
            # Enrutamiento decisivo
            if estado in self.aptos_conditions:
                ready_list.append(cand_dict)
                metrics["aptos_para_maestro"] += 1
            else:
                not_ready_list.append(cand_dict)
                metrics["no_aptos_para_maestro"] += 1
                
        # 1. Leer y Evaluar la base automatizada
        try:
            with open(self.resolved_path, 'r', encoding='utf-8') as f_res:
                for line in f_res:
                    if not line.strip(): continue
                    cand = json.loads(line)
                    process_candidate(cand)
        except Exception as e:
            print(f"[!] Archivo resolved corrupto o mal formado: {e}")

        # 2. Leer y Evaluar la basura / revisión manual
        if self.manual_review_path.exists():
            try:
                with open(self.manual_review_path, 'r', encoding='utf-8') as f_man:
                    for line in f_man:
                        if not line.strip(): continue
                        cand = json.loads(line)
                        process_candidate(cand)
                        metrics["total_revisados_manual"] += 1
            except Exception as e:
                 print(f"[!] Archivo manual_review corrupto o mal formado: {e}")
                 
        # Escribir los embudos divididos
        with open(self.ready_file, 'w', encoding='utf-8') as f_ready:
            for item in ready_list:
                f_ready.write(json.dumps(item, ensure_ascii=False) + "\n")
                
        with open(self.not_ready_file, 'w', encoding='utf-8') as f_not_ready:
            for item in not_ready_list:
                f_not_ready.write(json.dumps(item, ensure_ascii=False) + "\n")
                
        # Construir y Grabar Auditoria
        audit = {
            "lote_base": self.lote_base,
            "fecha_auditoria": datetime.now().isoformat(),
            "resumen": metrics,
            "reglas_auditoria": {
                "estados_aptos": self.aptos_conditions
            }
        }
        
        with open(self.report_file, 'w', encoding='utf-8') as f_rep:
            json.dump(audit, f_rep, ensure_ascii=False, indent=2)

        print(f"=========================================")
        print(f" AUDITORÍA DE RESOLUCIÓN (PASO 7.5) ")
        print(f"=========================================")
        print(f"  Total Candidatos      : {metrics['total_evaluados']}")
        print(f"  Aptos para Maestro    : {metrics['aptos_para_maestro']}")
        print(f"  No Aptos (Pendientes) : {metrics['no_aptos_para_maestro']}")
        print(f"-----------------------------------------")
        for est, amount in metrics["desglose_estados"].items():
            print(f"   -> {est.ljust(30)}: {amount}")
        print(f"=========================================")
        print(f"[*] Aprobados : {self.ready_file.name}")
        print(f"[*] Rechazados: {self.not_ready_file.name}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Paso 7.5: Auditoría y separación de candidatos resueltos.")
    parser.add_argument("--resolved_path", required=True, help="Ruta de candidates resueltos (resolved_...)")
    parser.add_argument("--manual_review_path", required=False, help="Ruta de candidates en manual_review")
    parser.add_argument("--output_dir", required=True, help="Directorio para outputs")
    
    args = parser.parse_args()
    
    # Derivar nombre de manual_review si no fue provisto
    manual_path = args.manual_review_path
    if not manual_path:
        # Calcularlo asumiendo nombres estandar
        lote_calc = Path(args.resolved_path).name.replace("resolved_", "").replace(".jsonl", "")
        manual_path = str(Path(args.output_dir) / f"manual_review_{lote_calc}.jsonl")
        
    evaluator = ResolutionEvaluator(args.resolved_path, manual_path, args.output_dir)
    evaluator.evaluate()
