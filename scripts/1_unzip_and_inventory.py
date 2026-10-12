import os
import zipfile
import json
import argparse
import shutil
import hashlib
import uuid
from pathlib import Path
from datetime import datetime

def calcular_sha256(filepath):
    sha256_hash = hashlib.sha256()
    with open(filepath, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def process_zip(zip_path_str, temp_dir_str):
    zip_path = Path(zip_path_str).resolve()
    temp_dir = Path(temp_dir_str).resolve()
    
    if not zip_path.exists():
        print(f"ERROR: No se encontró el archivo {zip_path}")
        return

    lote_name = zip_path.name
    extract_to = temp_dir / zip_path.stem
    
    if extract_to.exists():
        shutil.rmtree(extract_to)
    extract_to.mkdir(parents=True, exist_ok=True)
    
    # Métricas del reporte ajustadas
    total_archivos_encontrados = 0
    total_pdfs_detectados = 0
    total_pdfs_extraidos_ok = 0
    total_archivos_ignorados = 0
    total_errores = 0
    lista_errores = []
    inventory = []

    print(f"[*] Escaneando y extrayendo '{lote_name}' en:\n    {extract_to}")
    
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            for member in zip_ref.infolist():
                if member.is_dir():
                    continue

                total_archivos_encontrados += 1
                file_path = Path(member.filename)
                
                if file_path.suffix.lower() == '.pdf':
                    total_pdfs_detectados += 1
                    try:
                        # Prevención de Zip Slip (Path Traversal)
                        member_target_path = (extract_to / member.filename).resolve()
                        if not str(member_target_path).startswith(str(extract_to)):
                            raise ValueError(f"Intento de Path Traversal bloqueado (Zip Slip) en archivo: {member.filename}")
                        
                        # Extraer archivo individual
                        extracted_path = zip_ref.extract(member, extract_to)
                        abs_path = Path(extracted_path).resolve()
                        
                        rel_path = str(file_path).replace('\\', '/')
                        abs_path_str = str(abs_path).replace('\\', '/')
                        
                        # Generar identificadores y metadatos
                        id_doc = str(uuid.uuid4())
                        tamanio = abs_path.stat().st_size
                        hash_file = calcular_sha256(abs_path)
                        
                        inventory.append({
                            "id_documento": id_doc,
                            "lote": lote_name,
                            "archivo_origen": file_path.name,
                            "ruta_relativa_en_zip": rel_path,
                            "ruta_absoluta_temp": abs_path_str,
                            "tamano_bytes": tamanio,
                            "hash_sha256": hash_file
                        })
                        total_pdfs_extraidos_ok += 1
                        
                    except Exception as e:
                        total_errores += 1
                        lista_errores.append({
                            "archivo": member.filename,
                            "error": str(e)
                        })
                else:
                    total_archivos_ignorados += 1
                    
    except zipfile.BadZipFile:
        print(f"ERROR: El archivo '{zip_path}' no es un ZIP válido o está totalmente corrupto.")
        return

    # Guardar inventario
    inventory_file = extract_to / "inventory.json"
    with open(inventory_file, 'w', encoding='utf-8') as f:
        json.dump(inventory, f, ensure_ascii=False, indent=2)
        
    # Guardar reporte del lote
    report = {
        "lote_procesado": lote_name,
        "fecha_ejecucion": datetime.now().isoformat(),
        "total_archivos_encontrados": total_archivos_encontrados,
        "total_pdfs_detectados": total_pdfs_detectados,
        "total_pdfs_extraidos_ok": total_pdfs_extraidos_ok,
        "total_archivos_ignorados": total_archivos_ignorados,
        "total_errores": total_errores,
        "lista_errores": lista_errores
    }
    report_file = extract_to / "batch_report.json"
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"[*] Inventario guardado en: {inventory_file}")
    print(f"[*] Reporte de lote guardado en: {report_file}")
    print(f"=========================================")
    print(f" RESUMEN DEL LOTE: {lote_name}")
    print(f"=========================================")
    print(f" Archivos encontrados     : {total_archivos_encontrados}")
    print(f" PDFs detectados en ZIP   : {total_pdfs_detectados}")
    print(f" PDFs extraídos con éxito : {total_pdfs_extraidos_ok}")
    print(f" Archivos no compatibles  : {total_archivos_ignorados}")
    print(f" Errores de extracción    : {total_errores}")
    print(f"=========================================")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Descomprime un ZIP, previene Zip Slip y genera inventario enriquecido.")
    parser.add_argument("--zip_path", required=True, help="Ruta absoluta al archivo ZIP de entrada")
    parser.add_argument("--temp_dir", required=True, help="Directorio temporal base de salida")
    args = parser.parse_args()
    
    process_zip(args.zip_path, args.temp_dir)
