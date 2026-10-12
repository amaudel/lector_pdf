import os
import json
import argparse
import sys
from pathlib import Path
from datetime import datetime

# Importación dinámica del adaptador correspondiente
parent_dir = str(Path(__file__).resolve().parent)
if parent_dir not in sys.path: sys.path.append(parent_dir)

try:
    from adapters.router import SourceRouter
except ImportError as e:
    print(f"Error cargando los adaptadores/router: {e}")
    sys.exit(1)

def resolve_candidates(candidates_path_str, output_dir_str, adapter_name="mock"):
    candidates_path = Path(candidates_path_str).resolve()
    output_dir = Path(output_dir_str).resolve()

    if not candidates_path.exists():
        print(f"ERROR: No se encontró el archivo de candidatos en {candidates_path}")
        sys.exit(1)
        
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Derivar nombre del lote
    filename = candidates_path.name
    lote_base = filename.replace("candidates_", "").replace(".jsonl", "")
    
    resolved_file = output_dir / f"resolved_{lote_base}.jsonl"
    manual_review_file = output_dir / f"manual_review_{lote_base}.jsonl"
    report_file = output_dir / f"resolution_report_{lote_base}.json"

    print(f"[*] Iniciando Motor de Resolución (Fase 3) del lote '{lote_base}' con adaptador '{adapter_name}'...")
    
    # Iniciar motor adaptador (Router Inteligente)
    router = SourceRouter()
    
    total_leidos = 0
    conteo_rutas = {"RUTA_A": 0, "RUTA_B": 0, "RUTA_C": 0}
    
    resultados_estados = {
        "RUC_EXTRAIDO_DEL_PDF": 0,
        "COINCIDENCIA_DATASET_LOCAL_ALTA": 0,
        "COINCIDENCIA_DATASET_LOCAL_MEDIA": 0,
        "AMBIGUO_DATASET_LOCAL": 0,
        "SIN_RESULTADO_DATASET": 0,
        "VALIDADO_EXTERNAMENTE": 0,
        "AMBIGUO_EXTERNAMENTE": 0,
        "SIN_RESULTADO_EXTERNO": 0,
        "REVISION_MANUAL": 0
    }
    
    resolved_list = []
    manual_list = []
    
    with open(candidates_path, 'r', encoding='utf-8') as f_in:
        for line in f_in:
            if not line.strip(): continue
            try:
                candidato = json.loads(line)
                total_leidos += 1
                
                estado_cand = candidato.get("estado_candidato")
                ruc_texto = candidato.get("ruc_detectado_en_texto")
                if isinstance(ruc_texto, str) and ruc_texto.strip().lower() in ["null", "none", ""]:
                    ruc_texto = None
                
                # Molde base de resolución
                base_record = {
                    "lote": candidato.get("lote"),
                    "razon_social_candidata": candidato.get("razon_social_original"),
                    "razon_social_normalizada": candidato.get("razon_social_normalizada"),
                    "ruc_detectado_en_texto": ruc_texto,
                    "ruc_final": ruc_texto,
                    "fuente_ruc": "TEXTO_PDF" if ruc_texto else None,
                    "estado_resolucion": None,
                    "fuente_consultada": "DEDUPLICADOR_INTERNO",
                    "coincidencia_nombre": None,
                    "coincidencia_provincia": None,
                    "observaciones": "",
                    "candidato_original": candidato  # Trazabilidad total encapsulada
                }

                # Evaluador de rutas
                if estado_cand in ["REVISAR", "DESCARTAR"]:
                    # RUTA C - Intervención Manual (Evidencia Débil)
                    conteo_rutas["RUTA_C"] += 1
                    base_record["estado_resolucion"] = "REVISION_MANUAL"
                    base_record["observaciones"] = f"Derivado explícitamente a revisión por estado inicial de limpieza: {estado_cand}"
                    manual_list.append(base_record)
                    
                else:
                    # En LISTA_PARA_BUSQUEDA
                    if ruc_texto:
                        # RUTA A - Resolución local directa
                        conteo_rutas["RUTA_A"] += 1
                        base_record["estado_resolucion"] = "RUC_EXTRAIDO_DEL_PDF"
                        base_record["observaciones"] = "RUC capturado textualmente y consolidado sin necesidad de enriquecimiento externo."
                        resolved_list.append(base_record)
                        
                    else:
                        # RUTA B - Requerimiento de Búsqueda Externa (Inteligente por Tipología)
                        conteo_rutas["RUTA_B"] += 1
                        base_record["observaciones"] = "Inyección en Router Inteligente de Fuentes."
                        
                        resultado_rutas = router.route_for_completion(candidato)
                        
                        # Sobrescritura desde el router/validador
                        base_record["ruc_final"] = resultado_rutas["ruc_final"]
                        if base_record["ruc_final"]:
                            base_record["fuente_ruc"] = resultado_rutas["fuente_consultada"]
                            
                        base_record["estado_resolucion"] = resultado_rutas["estado_resolucion"]
                        base_record["fuente_consultada"] = resultado_rutas["fuente_consultada"]
                        base_record["coincidencia_nombre"] = resultado_rutas["coincidencia_nombre"]
                        base_record["coincidencia_provincia"] = resultado_rutas["coincidencia_provincia"]
                        base_record["provincia_oficial"] = resultado_rutas.get("provincia_oficial")
                        base_record["sucursal_azuay"] = resultado_rutas.get("sucursal_azuay", "NO")
                        
                        obs_router = resultado_rutas.get("observaciones", "")
                        base_record["observaciones"] += f" | Rslt: {obs_router}"
                        
                        resolved_list.append(base_record)
                        
            except Exception as e:
                print(f"[!] Archivo con estructura JSONL corrupta en línea: {e}")

    # Acumular marcadores de estados para el reporte
    for r in resolved_list:
        if r["estado_resolucion"] in resultados_estados:
            resultados_estados[r["estado_resolucion"]] += 1
    for m in manual_list:
        if m["estado_resolucion"] in resultados_estados:
            resultados_estados[m["estado_resolucion"]] += 1

    # Escritura física
    with open(resolved_file, 'w', encoding='utf-8') as f_res:
        for val in resolved_list:
            f_res.write(json.dumps(val, ensure_ascii=False) + "\n")
            
    with open(manual_review_file, 'w', encoding='utf-8') as f_man:
        for man in manual_list:
            f_man.write(json.dumps(man, ensure_ascii=False) + "\n")
            
    # Redactar bitácora oficial
    reporte = {
        "lote_base": lote_base,
        "fecha_resolucion": datetime.now().isoformat(),
        "adapter_configurado": adapter_name,
        "metricas": {
            "total_candidatos_analizados": total_leidos,
            "distribucion_de_rutas": conteo_rutas
        },
        "desglose_por_estados_finales": resultados_estados
    }
    
    with open(report_file, 'w', encoding='utf-8') as f_rep:
        json.dump(reporte, f_rep, ensure_ascii=False, indent=2)

    print(f"=========================================")
    print(f" MOTOR DE RESOLUCIÓN (FASE 3) ")
    print(f"=========================================")
    print(f" Evaluados             : {total_leidos}")
    print(f" [RUTA A] RUC Local    : {conteo_rutas['RUTA_A']}")
    print(f" [RUTA B] Red Externa  : {conteo_rutas['RUTA_B']}")
    print(f" [RUTA C] Para Humano  : {conteo_rutas['RUTA_C']}")
    print(f"-----------------------------------------")
    print(f" -> RUCs Confirmados PDF : {resultados_estados['RUC_EXTRAIDO_DEL_PDF']}")
    print(f" -> DB Local EXACTAS     : {resultados_estados['COINCIDENCIA_DATASET_LOCAL_ALTA']}")
    print(f" -> DB Local PARCIALES   : {resultados_estados['COINCIDENCIA_DATASET_LOCAL_MEDIA']}")
    print(f" -> DB Local AMBIGUOS    : {resultados_estados['AMBIGUO_DATASET_LOCAL']}")
    print(f" -> Miss Local/Externo   : {resultados_estados['SIN_RESULTADO_DATASET'] + resultados_estados['SIN_RESULTADO_EXTERNO']}")
    print(f" -> Revisión Manual      : {resultados_estados['REVISION_MANUAL']}")
    print(f"=========================================")
    print(f"[*] Base Extendida   : {resolved_file}")
    print(f"[*] Sink Manual      : {manual_review_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Paso 7: Resuelve candidatos mediante Motor Enchufable.")
    parser.add_argument("--candidates_path", required=True, help="Ruta absoluta a candidates_[lote].jsonl")
    parser.add_argument("--output_dir", required=True, help="Ruta de salida")
    parser.add_argument("--adapter", default="mock", help="Adapter a utilizar (ej. mock, sri)")
    args = parser.parse_args()
    
    resolve_candidates(args.candidates_path, args.output_dir, args.adapter)
