import os
import json
import argparse
import sys
from pathlib import Path
from datetime import datetime

def consolidate_batch(inventory_path_str, output_dir_str):
    inventory_path = Path(inventory_path_str).resolve()
    temp_dir = inventory_path.parent
    report_step2_path = temp_dir / "text_extraction_report.json"
    extracted_text_dir = temp_dir / "extracted_text"
    output_dir = Path(output_dir_str).resolve()

    if not inventory_path.exists():
        print(f"ERROR: No se encontró el inventario en {inventory_path}")
        sys.exit(1)
        
    output_dir.mkdir(parents=True, exist_ok=True)

    with open(inventory_path, 'r', encoding='utf-8') as f:
        inventory = json.load(f)

    if not inventory:
        print("ERROR: Inventario vacío.")
        sys.exit(1)

    # Distinguir entre lote_archivo y lote_base
    lote_archivo = inventory[0]["lote"] 
    lote_base = Path(lote_archivo).stem if lote_archivo.lower().endswith('.zip') else lote_archivo
    
    # Rutas finales usando lote_base
    consolidated_file = output_dir / f"consolidated_{lote_base}.jsonl"
    final_report_file = output_dir / f"final_batch_report_{lote_base}.json"

    print(f"[*] Iniciando consolidación del lote '{lote_base}' (Archivo original: {lote_archivo})...")
    
    # Mapeo de inventario (id_documento -> doc)
    inventory_ids = {doc.get("id_documento", "sin_id"): doc for doc in inventory}
    
    # Identificar JSONLs físicos existentes
    jsonl_files = list(extracted_text_dir.glob("*.jsonl")) if extracted_text_dir.exists() else []
    jsonl_ids = {f.stem: f for f in jsonl_files}

    inconsistencias = []
    
    total_documentos_con_salida_jsonl = 0
    total_documentos_faltantes_jsonl = 0
    total_jsonl_huerfanos = 0

    # 1. Validar documentos en inventario respecto a la existencia de JSONL
    for doc_id, doc in inventory_ids.items():
        if doc_id in jsonl_ids:
            total_documentos_con_salida_jsonl += 1
        else:
            total_documentos_faltantes_jsonl += 1
            inconsistencias.append({
                "tipo": "FALTANTE",
                "id_documento": doc_id,
                "archivo_origen": doc["archivo_origen"],
                "detalle": "Documento inventariado pero sin archivo JSONL generado."
            })

    # 2. Validar JSONLs huérfanos sin correspondencia en inventario
    for doc_id, file_path in jsonl_ids.items():
        if doc_id not in inventory_ids:
            total_jsonl_huerfanos += 1
            inconsistencias.append({
                "tipo": "HUERFANO",
                "id_documento": doc_id,
                "archivo_origen": "N/A",
                "detalle": "Archivo JSONL hallado pero no pertenece a la corrida vigente del inventario."
            })

    # Campos mínimos exigidos por cada registro de texto
    campos_requeridos = {
        "lote", "id_documento", "archivo_origen", "ruta_relativa_en_zip", 
        "pagina_pdf", "texto_crudo", "estado_extraccion"
    }

    # Consolidación de registros
    total_registros_consolidados = 0
    total_registros_invalidos = 0
    total_paginas_ok = 0
    total_paginas_sin_texto = 0
    total_paginas_con_error = 0
    lista_errores = []

    # Iterar sobre los archivos físicos encontrados en JSONL válidos
    with open(consolidated_file, 'w', encoding='utf-8') as out_f:
        for doc_id, file_path in jsonl_ids.items():
            if doc_id not in inventory_ids:
                continue 
                
            try:
                with open(file_path, 'r', encoding='utf-8') as in_f:
                    for line_num, line in enumerate(in_f, 1):
                        line = line.strip()
                        if not line:
                            continue
                        
                        try:
                            registro = json.loads(line)
                            
                            # Validación estructural de campos obligatorios por línea
                            campos_presentes = set(registro.keys())
                            faltantes = campos_requeridos - campos_presentes
                            
                            if faltantes:
                                total_registros_invalidos += 1
                                error_msg = f"Registro omitido. Faltan campos obligatorios: {faltantes}"
                                lista_errores.append({
                                    "archivo_jsonl": file_path.name,
                                    "linea": line_num,
                                    "error": error_msg
                                })
                                inconsistencias.append({
                                    "tipo": "REGISTRO_INVALIDO",
                                    "id_documento": doc_id,
                                    "archivo_origen": inventory_ids[doc_id]["archivo_origen"],
                                    "detalle": f"Línea {line_num} " + error_msg
                                })
                                continue
                            
                            estado = registro.get("estado_extraccion", "")
                            if estado == "OK":
                                total_paginas_ok += 1
                            elif estado == "SIN_TEXTO":
                                total_paginas_sin_texto += 1
                            elif estado == "ERROR":
                                total_paginas_con_error += 1
                            
                            total_registros_consolidados += 1
                            out_f.write(line + "\n")
                            
                        except json.JSONDecodeError as e:
                            total_registros_invalidos += 1
                            lista_errores.append({
                                "archivo_jsonl": file_path.name,
                                "linea": line_num,
                                "error": f"JSON corrupto ignorado en linea: {str(e)}"
                            })
            except Exception as e:
                lista_errores.append({
                    "archivo_jsonl": file_path.name,
                    "error": f"No se pudo abrir o leer el archivo JSONL: {str(e)}"
                })

    # Construcción de Manifiesto Final
    report = {
        "lote_archivo": lote_archivo,
        "lote_base": lote_base,
        "fecha_consolidacion": datetime.now().isoformat(),
        "rutas_fuente": {
            "inventario": str(inventory_path).replace('\\', '/'),
            "reporte_paso_2": str(report_step2_path).replace('\\', '/') if report_step2_path.exists() else "NO_EXISTE",
            "carpeta_jsonl": str(extracted_text_dir).replace('\\', '/')
        },
        "rutas_salida_generadas": {
            "consolidado_jsonl": str(consolidated_file).replace('\\', '/'),
            "reporte_final": str(final_report_file).replace('\\', '/')
        },
        "documentos": {
            "total_documentos_inventariados": len(inventory_ids),
            "total_documentos_con_salida_jsonl": total_documentos_con_salida_jsonl,
            "total_documentos_faltantes_jsonl": total_documentos_faltantes_jsonl,
            "total_jsonl_huerfanos": total_jsonl_huerfanos
        },
        "registros": {
            "total_registros_consolidados": total_registros_consolidados,
            "total_registros_invalidos": total_registros_invalidos,
            "total_paginas_ok": total_paginas_ok,
            "total_paginas_sin_texto": total_paginas_sin_texto,
            "total_paginas_con_error": total_paginas_con_error
        },
        "inconsistencias": inconsistencias,
        "lista_errores": lista_errores
    }

    with open(final_report_file, 'w', encoding='utf-8') as rep_f:
        json.dump(report, rep_f, ensure_ascii=False, indent=2)

    print(f"[*] Consolidación exitosa del lote base '{lote_base}'")
    print(f"[*] Archivo Maestro: {consolidated_file}")
    print(f"[*] Manifiesto Final: {final_report_file}")
    print(f"=========================================")
    print(f" RESUMEN DE CONSOLIDACIÓN ")
    print(f"=========================================")
    print(f" Docs en Inventario    : {len(inventory_ids)}")
    print(f" Docs consolidados     : {total_documentos_con_salida_jsonl}")
    print(f" Páginas consolidadas  : {total_registros_consolidados}")
    print(f" Registros inválidos   : {total_registros_invalidos}")
    print(f" Inconsistencias Gen.  : {len(inconsistencias)}")
    print(f"=========================================")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Consolida archivos JSONL dispersos validándolos mediante cruce estricto de inventario.")
    parser.add_argument("--inventory_path", required=True, help="Ruta absoluta al inventory.json")
    parser.add_argument("--output_dir", required=True, help="Ruta absoluta a la carpeta data/output")
    args = parser.parse_args()
    
    consolidate_batch(args.inventory_path, args.output_dir)
