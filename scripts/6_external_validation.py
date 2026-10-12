import os
import json
import argparse
import sys
from pathlib import Path
from datetime import datetime

# ==========================================
# SIMULADOR DE BÚSQUEDA EXTERNA (Fase 3A)
# ==========================================
def mock_external_search(ruc, razon_social):
    """
    Simula una consulta a una API externa (SRI/Supercias).
    En esta fase MVP conservadora, no realizamos llamadas reales.
    """
    # TODO: Implementar lógica HTTP real hacia el scraper o API oficial
    return None

def validate_candidates(candidates_path_str, output_dir_str):
    candidates_path = Path(candidates_path_str).resolve()
    output_dir = Path(output_dir_str).resolve()

    if not candidates_path.exists():
        print(f"ERROR: No se encontró el archivo de candidatos en {candidates_path}")
        sys.exit(1)
        
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Derivar nombre del lote
    filename = candidates_path.name
    lote_base = filename.replace("candidates_", "").replace(".jsonl", "")
    
    validated_file = output_dir / f"validated_{lote_base}.jsonl"
    report_file = output_dir / f"validation_report_{lote_base}.json"

    print(f"[*] Iniciando Validación Externa (Fase 3A) del lote '{lote_base}'...")
    
    total_candidatos_leidos = 0
    total_procesados = 0
    total_omitidos = 0
    
    resultados = {
        "VALIDADO": 0,
        "PROBABLE": 0,
        "AMBIGUO": 0,
        "SIN_RESULTADO": 0,
        "REVISAR": 0,
        "NO_PROCESADO": 0
    }
    
    with open(candidates_path, 'r', encoding='utf-8') as f_in, open(validated_file, 'w', encoding='utf-8') as f_out:
        for line in f_in:
            if not line.strip(): continue
            try:
                candidato = json.loads(line)
                total_candidatos_leidos += 1
                
                # Base del registro de validación
                registro_val = {
                    "lote": candidato.get("lote"),
                    "razon_social_candidata": candidato.get("razon_social_normalizada") or candidato.get("razon_social_original"),
                    "ruc_candidato": candidato.get("ruc_detectado_en_texto"),
                    "fuente_consultada": "MOCK_LOCAL", # Cambiará a SRI / Supercias
                    "coincidencia_nombre": None,
                    "coincidencia_provincia": None,
                    "resultado_validacion": None,
                    "observaciones": "",
                    "candidato_original": candidato # Trazabilidad completa incrustada
                }
                
                estado_ingreso = candidato.get("estado_candidato")
                
                # Prioridad 1 y 2: Filtrar quién se procesa
                if estado_ingreso != "LISTA_PARA_BUSQUEDA":
                    registro_val["resultado_validacion"] = "NO_PROCESADO"
                    registro_val["observaciones"] = f"Omitido por estado inicial: {estado_ingreso}"
                    total_omitidos += 1
                else:
                    total_procesados += 1
                    
                    # Llamada a busqueda externa
                    resultado_externo = mock_external_search(
                        registro_val["ruc_candidato"], 
                        registro_val["razon_social_candidata"]
                    )
                    
                    if resultado_externo:
                        # TODO: Lógica real cuando haya datos
                        pass
                    else:
                        # Lógica conservadora sin resultado externo
                        if registro_val["ruc_candidato"]:
                            registro_val["resultado_validacion"] = "PROBABLE"
                            registro_val["observaciones"] = "Sin conexión externa. Pasa automátícamente a PROBABLE por poseer RUC explícito."
                        else:
                            registro_val["resultado_validacion"] = "SIN_RESULTADO"
                            registro_val["observaciones"] = "Sin conexión externa ni RUC. Imposible validar automáticamente."
                
                # Actualizar contadores y escribir
                estado_asignado = registro_val["resultado_validacion"]
                if estado_asignado in resultados:
                    resultados[estado_asignado] += 1
                    
                f_out.write(json.dumps(registro_val, ensure_ascii=False) + "\n")
                
            except Exception as e:
                print(f"[!] Error procesando candidato: {e}")
                
    # Generar Reporte de Fase 3A
    reporte = {
        "lote_base": lote_base,
        "fecha_validacion": datetime.now().isoformat(),
        "metricas": {
            "total_candidatos_leidos": total_candidatos_leidos,
            "total_procesados_busqueda_externa": total_procesados,
            "total_omitidos": total_omitidos
        },
        "desglose_resultados": resultados
    }
    
    with open(report_file, 'w', encoding='utf-8') as f_rep:
        json.dump(reporte, f_rep, ensure_ascii=False, indent=2)

    print(f"=========================================")
    print(f" RESUMEN DE VALIDACIÓN EXTERNA (FASE 3A) ")
    print(f"=========================================")
    print(f" Leídos       : {total_candidatos_leidos}")
    print(f" Procesados   : {total_procesados}")
    print(f" Omitidos     : {total_omitidos}")
    print(f" -> Probables : {resultados['PROBABLE']}")
    print(f" -> Sin Rslt  : {resultados['SIN_RESULTADO']}")
    print(f"=========================================")
    print(f"[*] Resultados: {validated_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Paso 6: Validar candidatos contra fuentes externas (Modelo MVP).")
    parser.add_argument("--candidates_path", required=True, help="Ruta absoluta a candidates_[lote].jsonl")
    parser.add_argument("--output_dir", required=True, help="Ruta de salida")
    args = parser.parse_args()
    
    validate_candidates(args.candidates_path, args.output_dir)
