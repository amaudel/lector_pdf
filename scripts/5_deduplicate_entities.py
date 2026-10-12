import os
import json
import argparse
import sys
import re
from pathlib import Path
from datetime import datetime

# ==========================================
# REGLAS DE NORMALIZACIÓN
# ==========================================
def normalize_business_name(name):
    if not name:
        return ""
    # Convertir a mayúsculas
    n = name.upper()
    # Reemplazar guiones bajos con espacios para unificar nombres de archivos
    n = n.replace('_', ' ')
    # Eliminar comillas y caracteres especiales comunes
    n = re.sub(r'[\"\'\“\”\.,;]', '', n)
    # Reemplazar múltiples espacios por uno solo
    n = re.sub(r'\s+', ' ', n)
    # Limpiar espacios al inicio y final
    n = n.strip()
    return n

def build_candidate_key(ruc, norm_name):
    # Clave de agrupación. Prioriza RUC. Si no hay, usa nombre normalizado.
    # En proyectos grandes, esto es el "Blocking Key".
    if ruc and ruc.strip() not in ["", "null", "None"]:
        return f"RUC:{ruc.strip()}"
    return f"NAME:{norm_name}"

def deduplicate_entities(entities_path_str, output_dir_str):
    entities_path = Path(entities_path_str).resolve()
    output_dir = Path(output_dir_str).resolve()

    if not entities_path.exists():
        print(f"ERROR: No se encontró el archivo de entidades en {entities_path}")
        sys.exit(1)
        
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Derivar nombre de lote_base 
    filename = entities_path.name
    lote_base = filename.replace("entities_extracted_", "").replace(".jsonl", "")
    
    candidates_file = output_dir / f"candidates_{lote_base}.jsonl"
    report_file = output_dir / f"candidates_report_{lote_base}.json"

    print(f"[*] Iniciando Depuración y Agrupación del lote '{lote_base}'...")
    
    raw_entities = []
    
    # Fase 1: Lectura y Normalización Básica
    with open(entities_path, 'r', encoding='utf-8') as f:
        for line in f:
            if not line.strip(): continue
            try:
                record = json.loads(line)
                # Omitir registros de control (páginas vacías)
                if record.get("estado_entidad") == "SIN_ENTIDAD_CLARA":
                    continue
                
                rz_original = record.get("razon_social_original") or ""
                rz_norm = normalize_business_name(rz_original)
                
                # Filtro estricto para entidades gubernamentales emisoras y de control
                filtro_ruido = [
                    "INSTITUTO ECUATORIANO DE SEGURIDAD SOCIAL", 
                    "SERVICIO DE RENTAS INTERNAS",
                    "SUPERINTENDENCIA DE COMPAÑÍAS VALORES Y SEGUROS",
                    "SUPERINTENDENCIA DE COMPAÑIAS VALORES Y SEGUROS",
                    "SUPERINTENDENCIA DE COMPANIAS VALORES Y SEGUROS",
                    "SUPERINTENDENCIA DE COMPAÑÍAS",
                    "SUPERINTENDENCIA DE COMPAÑIAS",
                    "SUPERINTENDENCIA DE COMPANIAS",
                    "SUPERCIAS",
                    "SUPER DE COMPAÑÍAS",
                    "SUPER DE COMPAÑIAS",
                    "SUPERINTENDENCIA DE BANCOS",
                    "CONTRALORÍA GENERAL DEL ESTADO",
                    "CONTRALORIA GENERAL DEL ESTADO",
                    "INTENDENCIA REGIONAL",
                    "INTENDENCIA DE COMPAÑÍAS",
                    "INTENDENCIA DE COMPAÑIAS",
                    "INTENDENCIA DE COMPANIAS",
                    "SUPERINTENDENCIA",
                    "INTENDENCIA",
                    "REGISTRO MERCANTIL",
                    "SERVICIO NACIONAL DE CONTRATACIÓN PÚBLICA",
                    "SERVICIO NACIONAL DE CONTRATACION PUBLICA",
                    "SERCOP"
                ]
                if any(ruido in rz_norm for ruido in filtro_ruido) or rz_norm in [
                    "IESS", "SRI", "SERVICIO DE RENTAS INTERNAS SRI", "INSTITUTO ECUATORIANO DE SEGURIDAD SOCIAL IESS",
                    "SUPERCIAS", "CONTRALORIA", "REGISTRO MERCANTIL", "SERCOP"
                ]:
                    continue

                # Excluir explícitamente placeholders y entidades basura/control (NONE, NULL, NOME, MASIVA, SCVS, etc.)
                check_name = rz_norm.strip()
                is_ruido_adicional = (
                    check_name in ["NONE", "NULL", "NOME", "UNKNOWN", "DESCONOCIDA", "DESCONOCIDO", "SIN DATO", "SIN_DATO", "NO DISPONIBLE", "COMPAÑIA", "COMPANIA", "COMPANIAS", "COMPAÑIAS", "EMPRESA", "EMPRESAS", "SOCIEDAD", "ASOCIACION", "ASOCIACIÓN", "CONSORCIO"] or
                    check_name.startswith("NONE ") or 
                    check_name.startswith("NULL ") or 
                    check_name.startswith("NOME ") or 
                    check_name.startswith("UNKNOWN ") or 
                    check_name.startswith("DESCONOCIDA ") or 
                    check_name.startswith("DESCONOCIDO ") or 
                    check_name.startswith("SIN DATO ") or 
                    "MASIVA" in rz_norm or 
                    rz_norm.startswith("SCVS") or
                    rz_norm.replace(" ", "").startswith("SCVS") or
                    len(check_name) < 3
                )
                if is_ruido_adicional:
                    continue

                # Validar RUC detectado (Ecuador: 13 dígitos numéricos terminados en 001)
                ruc = record.get("ruc_detectado_en_texto")
                if ruc:
                    ruc_clean = re.sub(r'\D', '', str(ruc).strip())
                    # Validar longitud (13 dígitos) y terminación
                    if len(ruc_clean) == 13 and ruc_clean.endswith("001"):
                        # Validar código de provincia (primeros 2 dígitos entre 01 y 24, o 30)
                        try:
                            prov_code = int(ruc_clean[:2])
                            if 1 <= prov_code <= 24 or prov_code == 30:
                                record["ruc_detectado_en_texto"] = ruc_clean
                            else:
                                record["ruc_detectado_en_texto"] = None
                        except ValueError:
                            record["ruc_detectado_en_texto"] = None
                    else:
                        record["ruc_detectado_en_texto"] = None

                record["razon_social_normalizada"] = rz_norm
                raw_entities.append(record)
            except Exception as e:
                print(f"[!] Archivo malformado en parsing JSON: {e}")

    # Fase 2: Descubrimiento de RUCs cruzados
    # Si una empresa tiene RUC en la pág 1 pero en la pág 5 solo mencionan su nombre, heredamos el RUC.
    name_to_ruc = {}
    for ent in raw_entities:
        ruc = ent.get("ruc_detectado_en_texto")
        norm_name = ent.get("razon_social_normalizada")
        if ruc and norm_name:
            # Asociamos el primer RUC válido encontrado a este nombre
            if norm_name not in name_to_ruc:
                name_to_ruc[norm_name] = ruc
                
    # Fase 3: Agrupación y Consolidación
    grouped_candidates = {}
    
    for ent in raw_entities:
        norm_name = ent.get("razon_social_normalizada", "")
        # Propagar RUC cruzado si está vacío en esta mención
        ruc = ent.get("ruc_detectado_en_texto")
        if not ruc and norm_name in name_to_ruc:
            ruc = name_to_ruc[norm_name]
            
        key = build_candidate_key(ruc, norm_name)
        
        if key not in grouped_candidates:
            grouped_candidates[key] = {
                "lote": ent.get("lote"),
                "razon_social_original_referencia": ent.get("razon_social_original"),
                "razon_social_normalizada": norm_name,
                "tipo_entidad_detectada": set(),
                "provincias_mencionadas": set(),
                "ruc_detectado_en_texto": ruc,
                "menciones_totales": 0,
                "archivos_origen": set(),
                "paginas_origen": set(),
                "fragmentos_evidencia": []
            }
            
        cand = grouped_candidates[key]
        cand["menciones_totales"] += 1
        
        if ent.get("tipo_entidad_detectada"): cand["tipo_entidad_detectada"].add(ent["tipo_entidad_detectada"])
        if ent.get("provincia_mencionada"): cand["provincias_mencionadas"].add(ent["provincia_mencionada"])
        if ent.get("archivo_origen"): cand["archivos_origen"].add(ent["archivo_origen"])
        if ent.get("pagina_pdf"): cand["paginas_origen"].add(ent["pagina_pdf"])
        
        # Conservar hasta 3 fragmentos de evidencia distintos para no inflar el archivo
        frag = ent.get("fragmento_evidencia")
        if frag and frag not in cand["fragmentos_evidencia"] and len(cand["fragmentos_evidencia"]) < 3:
            cand["fragmentos_evidencia"].append(frag)

    # Fase 4: Preparación Final de Candidatos
    final_candidates = []
    
    for key, data in grouped_candidates.items():
        prov_set = {p for p in data["provincias_mencionadas"] if p}
        if len(prov_set) == 1:
            prov_consistente = "SI"
        elif len(prov_set) > 1:
            prov_consistente = "NO"
        else:
            prov_consistente = "SIN_DATO"
            
        tipo_set = {t for t in data["tipo_entidad_detectada"] if t}
        if len(tipo_set) == 1:
            tipo_consistente = "SI"
        elif len(tipo_set) > 1:
            tipo_consistente = "NO"
        else:
            tipo_consistente = "SIN_DATO"
            
        ruc = data["ruc_detectado_en_texto"]
        # En esta fase, si el grupo tiene RUC, provino del texto de al menos una mención.
        ruc_fuente = "EXPLICITO_EN_TEXTO" if ruc else "NO_DISPONIBLE"

        # Heurística de Nivel de Confianza Global y Clasificación
        if ruc:
            confianza = "ALTA"
            estado = "LISTA_PARA_BUSQUEDA"
        elif data["razon_social_normalizada"]:
            # Enviamos a buscar CUALQUIER nombre extraído a la base maestra global
            # sin importar si apareció 1 sola vez. El router será el juez definitivo.
            confianza = "MEDIA" if data["menciones_totales"] >= 2 else "BAJA"
            estado = "LISTA_PARA_BUSQUEDA"
        else:
            confianza = "BAJA"
            estado = "DESCARTAR"
            
        # Serialización de candidato
        final_cand = {
            "lote": data["lote"],
            "razon_social_original": data["razon_social_original_referencia"],
            "razon_social_normalizada": data["razon_social_normalizada"],
            "tipo_entidad_detectada": list(tipo_set)[0] if tipo_set else None,
            "provincia_mencionada": list(prov_set)[0] if prov_set else None,
            "ruc_detectado_en_texto": ruc,
            "ruc_fuente": ruc_fuente,
            "provincia_consistente": prov_consistente,
            "tipo_consistente": tipo_consistente,
            "menciones_totales": data["menciones_totales"],
            "archivos_origen": list(data["archivos_origen"]),
            "paginas_origen": sorted(list(data["paginas_origen"])),
            "fragmentos_evidencia": data["fragmentos_evidencia"],
            "nivel_confianza_global": confianza,
            "estado_candidato": estado
        }
        final_candidates.append(final_cand)

    # Escribir salida consolidada
    with open(candidates_file, 'w', encoding='utf-8') as f_out:
        for cand in final_candidates:
            f_out.write(json.dumps(cand, ensure_ascii=False) + "\n")
            
    # Escribir reporte
    resumen = {
        "lote_base": lote_base,
        "fecha_depuracion": datetime.now().isoformat(),
        "entidades_crudas_procesadas": len(raw_entities),
        "candidatos_unicos_generados": len(final_candidates),
        "desglose_por_estado": {
            "lista_para_busqueda": sum(1 for c in final_candidates if c["estado_candidato"] == "LISTA_PARA_BUSQUEDA"),
            "revisar": sum(1 for c in final_candidates if c["estado_candidato"] == "REVISAR"),
            "descartar": sum(1 for c in final_candidates if c["estado_candidato"] == "DESCARTAR")
        }
    }
    
    with open(report_file, 'w', encoding='utf-8') as f_rep:
        json.dump(resumen, f_rep, ensure_ascii=False, indent=2)

    print(f"=========================================")
    print(f" RESUMEN DE PURIFICACIÓN (FASE 2.5) ")
    print(f"=========================================")
    print(f" Menciones crudas     : {resumen['entidades_crudas_procesadas']}")
    print(f" Empresas/Candidatos  : {resumen['candidatos_unicos_generados']}")
    print(f" Listos p/ Búsqueda   : {resumen['desglose_por_estado']['lista_para_busqueda']}")
    print(f" Para revisión manual : {resumen['desglose_por_estado']['revisar']}")
    print(f"=========================================")
    print(f"[*] Resultados: {candidates_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Paso 5: Depurar y agrupar entidades en candidatos únicos.")
    parser.add_argument("--entities_path", required=True, help="Ruta absoluta al entities_extracted_[lote].jsonl")
    parser.add_argument("--output_dir", required=True, help="Ruta de salida (habitualmente data/output)")
    args = parser.parse_args()
    
    deduplicate_entities(args.entities_path, args.output_dir)
