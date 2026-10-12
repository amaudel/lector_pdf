import fitz  # PyMuPDF
import json
import argparse
import sys
from pathlib import Path
from datetime import datetime

def extract_pdf_pages(inventory_path_str):
    inventory_path = Path(inventory_path_str).resolve()
    if not inventory_path.exists():
        print(f"ERROR: No se encontró el inventario en {inventory_path}")
        sys.exit(1)

    with open(inventory_path, 'r', encoding='utf-8') as f:
        inventory = json.load(f)

    if not inventory:
        print("El inventario está vacío. No hay PDFs registrados para procesar.")
        sys.exit(0)

    # El directorio destino de la extracción se ubicará al lado del inventario
    lote_dir = inventory_path.parent
    extracted_text_dir = lote_dir / "extracted_text"
    
    # Limpiar el directorio si existía para garantizar idempotencia por corrida
    import shutil
    if extracted_text_dir.exists():
        shutil.rmtree(extracted_text_dir)
    extracted_text_dir.mkdir(parents=True, exist_ok=True)

    # Identificar el nombre del lote basándonos en el primer registro
    lote_name = inventory[0]["lote"] if len(inventory) > 0 else "unknown_lote"

    total_documentos_procesados = len(inventory)
    print(f"[*] Iniciando extracción de texto para {total_documentos_procesados} documentos en:\n    {extracted_text_dir}")

    # Métricas del reporte
    total_documentos_ok = 0
    total_documentos_con_error = 0
    total_paginas_procesadas = 0
    total_paginas_ok = 0
    total_paginas_sin_texto = 0
    total_paginas_con_error = 0
    lista_errores = []

    for doc in inventory:
        doc_path = Path(doc["ruta_absoluta_temp"])
        lote = doc["lote"]
        id_doc = doc.get("id_documento", "sin_id")
        archivo = doc["archivo_origen"]
        rel_path = doc["ruta_relativa_en_zip"]
        
        # Archivo de salida basado íntegramente en el ID del documento para evitar colisiones
        jsonl_path = extracted_text_dir / f"{id_doc}.jsonl"
        
        print(f"  -> Procesando: {rel_path}", end=" ")
        
        doc_ok = True
        doc_pages_count = 0
        try:
            with fitz.open(doc_path) as pdf:
                doc_pages_count = len(pdf)
                with open(jsonl_path, 'w', encoding='utf-8') as out_f:
                    for page_num in range(doc_pages_count):
                        total_paginas_procesadas += 1
                        pagina_pdf = page_num + 1
                        
                        try:
                            # Aislamiento por página
                            page = pdf[page_num]
                            texto = page.get_text("text").strip()
                            tamano_texto = len(texto)
                            
                            estado = "OK"
                            if tamano_texto == 0:
                                # SIN_TEXTO indica únicamente que este método crudo no halló strings recuperables. No asume OCR
                                estado = "SIN_TEXTO"
                                total_paginas_sin_texto += 1
                            else:
                                total_paginas_ok += 1
                            
                            registro = {
                                "lote": lote,
                                "id_documento": id_doc,
                                "archivo_origen": archivo,
                                "ruta_relativa_en_zip": rel_path,
                                "pagina_pdf": pagina_pdf,
                                "total_paginas_documento": doc_pages_count,
                                "fecha_extraccion": datetime.now().isoformat(),
                                "tamano_texto": tamano_texto,
                                "texto_crudo": texto,
                                "estado_extraccion": estado,
                                "detalle_error": ""
                            }
                            out_f.write(json.dumps(registro, ensure_ascii=False) + "\n")
                            
                        except Exception as page_e:
                            # Captura de error a nivel Página
                            total_paginas_con_error += 1
                            doc_ok = False
                            error_msg = f"Error en pág {pagina_pdf}: {str(page_e)}"
                            lista_errores.append({
                                "archivo": archivo,
                                "id_documento": id_doc,
                                "pagina": pagina_pdf,
                                "error": error_msg
                            })
                            
                            registro = {
                                "lote": lote,
                                "id_documento": id_doc,
                                "archivo_origen": archivo,
                                "ruta_relativa_en_zip": rel_path,
                                "pagina_pdf": pagina_pdf,
                                "total_paginas_documento": doc_pages_count,
                                "fecha_extraccion": datetime.now().isoformat(),
                                "tamano_texto": 0,
                                "texto_crudo": "",
                                "estado_extraccion": "ERROR",
                                "detalle_error": str(page_e)
                            }
                            out_f.write(json.dumps(registro, ensure_ascii=False) + "\n")

            # Finalizó de leer todas las páginas del doc
            if doc_ok:
                print(f"[OK] ({doc_pages_count} págs)")
                total_documentos_ok += 1
            else:
                print(f"[PARCIAL] (Errores en algunas págs)")
                total_documentos_con_error += 1
                
        except Exception as doc_e:
            # Captura de error Crítico a nivel Abriendo Documento
            print(f"[ERROR CRÍTICO] ({doc_e})")
            total_documentos_con_error += 1
            lista_errores.append({
                "archivo": archivo,
                "id_documento": id_doc,
                "pagina": "N/A",
                "error": f"Error abriendo documento: {str(doc_e)}"
            })
            
            # Registrar al menos una fila informando la caída estructural
            with open(jsonl_path, 'w', encoding='utf-8') as out_f:
                registro = {
                    "lote": lote,
                    "id_documento": id_doc,
                    "archivo_origen": archivo,
                    "ruta_relativa_en_zip": rel_path,
                    "pagina_pdf": 0,
                    "total_paginas_documento": 0,
                    "fecha_extraccion": datetime.now().isoformat(),
                    "tamano_texto": 0,
                    "texto_crudo": "",
                    "estado_extraccion": "ERROR",
                    "detalle_error": str(doc_e)
                }
                out_f.write(json.dumps(registro, ensure_ascii=False) + "\n")

    # Finalizado el ciclo de docs, guardar reporte de extracción
    report = {
        "lote_procesado": lote_name,
        "fecha_ejecucion": datetime.now().isoformat(),
        "total_documentos_procesados": total_documentos_procesados,
        "total_documentos_ok": total_documentos_ok,
        "total_documentos_con_error": total_documentos_con_error,
        "total_paginas_procesadas": total_paginas_procesadas,
        "total_paginas_ok": total_paginas_ok,
        "total_paginas_sin_texto": total_paginas_sin_texto,
        "total_paginas_con_error": total_paginas_con_error,
        "lista_errores": lista_errores
    }
    
    report_file = lote_dir / "text_extraction_report.json"
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n=========================================")
    print(f" RESUMEN DE EXTRACCIÓN DE TEXTO")
    print(f"=========================================")
    print(f" Docs procesados   : {total_documentos_procesados}")
    print(f" Docs OK           : {total_documentos_ok}")
    print(f" Docs con Error    : {total_documentos_con_error}")
    print(f" Páginas OK        : {total_paginas_ok}")
    print(f" Páginas SIN_TEXTO : {total_paginas_sin_texto}")
    print(f" Páginas con ERROR : {total_paginas_con_error}")
    print(f"=========================================")
    print(f"[*] Reporte exportado en: {report_file}")
    print(f"[*] JSONLs consolidados en: {extracted_text_dir}/")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extrae iterativamente el texto base de PDFs produciendo JSONL aislados y un Manifiesto.")
    parser.add_argument("--inventory_path", required=True, help="Ruta absoluta a inventory.json")
    args = parser.parse_args()
    
    extract_pdf_pages(args.inventory_path)
