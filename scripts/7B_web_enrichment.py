"""
=============================================================================
 PASO 7B — WEB ENRICHMENT LAYER
=============================================================================
 Enriquece entidades SIN RUC usando fuentes web externas (mock o reales).
 
 - NO alimenta directamente al maestro.
 - NO sobreescribe datos existentes.
 - Genera un archivo consultivo para re-evaluación humana o automática.
 
 Scoring ponderado:
   nombre 55% | provincia 20% | tipo_entidad 15% | unicidad 10%
 
 Umbrales:
   CONFIRMADO_WEB >= 0.90
   PROBABLE_WEB   0.75 – 0.89
   AMBIGUO_WEB    0.55 – 0.74
   NO_ENCONTRADO  < 0.55 o sin match
=============================================================================
"""
import os
import sys
import json
import re
import argparse
from pathlib import Path
from datetime import datetime

# Añadir el directorio padre al path para importar adapters
sys.path.insert(0, str(Path(__file__).resolve().parent))

from adapters.seps_web import SepsWebAdapter
from adapters.supercias_web import SuperciasWebAdapter
from adapters.sri_web import SriWebAdapter


# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURACIÓN DE SCORING
# ─────────────────────────────────────────────────────────────────────────────
PESO_NOMBRE    = 0.55
PESO_PROVINCIA = 0.20
PESO_TIPO      = 0.15
PESO_UNICIDAD  = 0.10

UMBRAL_CONFIRMADO = 0.90
UMBRAL_PROBABLE   = 0.75
UMBRAL_AMBIGUO    = 0.55

# Tipos de entidad que van a cada adapter
TIPOS_COOPERATIVA = {"COOPERATIVA", "COOP", "COOPERATIVA DE AHORRO", "COOPERATIVA DE TRANSPORTE"}
TIPOS_COMPANIA    = {"COMPAÑIA", "COMPANIA", "S.A.", "C.LTDA.", "CIA", "CIA. LTDA.", "SOCIEDAD ANONIMA", "C.A."}


# ─────────────────────────────────────────────────────────────────────────────
# FUNCIONES DE SCORING
# ─────────────────────────────────────────────────────────────────────────────
def normalizar(texto: str) -> str:
    """Normaliza un texto para comparación."""
    if not texto:
        return ""
    texto = texto.upper().strip()
    texto = re.sub(r'[^A-Z0-9\s]', '', texto)
    texto = re.sub(r'\s+', ' ', texto)
    return texto


def limpiar_razon_social(texto: str) -> str:
    """
    Limpia una razón social sucia antes de buscarla.
    Remueve extensiones de archivo, underscores, comillas tipográficas, etc.
    Retorna un texto legible sin perder semántica.
    """
    if not texto:
        return ""
    # Remover extensiones de archivo
    texto = re.sub(r'\.(zip|pdf|jsonl|json|xlsx|csv)$', '', texto, flags=re.IGNORECASE)
    # Reemplazar underscores por espacios
    texto = texto.replace('_', ' ')
    # Remover comillas tipográficas y normales
    texto = re.sub(r'[\u201c\u201d\u201e\u201f\u2018\u2019\u00ab\u00bb"\'`]', '', texto)
    # Limpiar dobles espacios
    texto = re.sub(r'\s+', ' ', texto)
    return texto.strip()


def similitud_levenshtein(s1: str, s2: str) -> float:
    """Calcula la similitud normalizada entre dos cadenas (1.0 = idénticas)."""
    if not s1 or not s2:
        return 0.0
    s1, s2 = normalizar(s1), normalizar(s2)
    if s1 == s2:
        return 1.0
    
    len1, len2 = len(s1), len(s2)
    max_len = max(len1, len2)
    if max_len == 0:
        return 0.0
    
    # Matriz de distancia Levenshtein
    matrix = [[0] * (len2 + 1) for _ in range(len1 + 1)]
    for i in range(len1 + 1):
        matrix[i][0] = i
    for j in range(len2 + 1):
        matrix[0][j] = j
    
    for i in range(1, len1 + 1):
        for j in range(1, len2 + 1):
            cost = 0 if s1[i - 1] == s2[j - 1] else 1
            matrix[i][j] = min(
                matrix[i - 1][j] + 1,
                matrix[i][j - 1] + 1,
                matrix[i - 1][j - 1] + cost
            )
    
    distancia = matrix[len1][len2]
    return 1.0 - (distancia / max_len)


def calcular_score_provincia(provincia_pdf: str, provincia_web: str) -> float:
    """Score de coincidencia de provincia."""
    if not provincia_pdf or provincia_pdf == "SIN_DATO":
        return 0.5  # No hay dato en PDF, neutral
    if not provincia_web:
        return 0.0  # Web no reportó provincia
    if normalizar(provincia_pdf) == normalizar(provincia_web):
        return 1.0  # Coincide
    return 0.0  # Contradice


def calcular_score_tipo(tipo_entidad: str, fuente_adapter: str) -> float:
    """Score de coherencia entre tipo de entidad y fuente consultada."""
    tipo_norm = normalizar(tipo_entidad)
    
    if fuente_adapter == "SEPS" and any(t in tipo_norm for t in ["COOPERATIVA", "COOP"]):
        return 1.0  # Cooperativa buscada en SEPS, coherente
    elif fuente_adapter == "SUPERCIAS" and any(t in tipo_norm for t in ["COMPANIA", "CIA", "SA", "CA"]):
        return 1.0  # Compañía buscada en Supercias, coherente
    elif fuente_adapter == "SRI":
        return 0.5  # SRI es fuente genérica, coherencia neutral
    
    return 0.5  # Adapter de fallback, coherencia parcial


def calcular_score_unicidad(num_resultados: int) -> float:
    """Score basado en cuántos resultados devolvió la fuente."""
    if num_resultados == 1:
        return 1.0
    elif num_resultados <= 3:
        return 0.5
    else:
        return 0.0


def calcular_score_total(sim_nombre, match_prov, match_tipo, unicidad) -> float:
    """Calcula el score ponderado total."""
    return (sim_nombre * PESO_NOMBRE
          + match_prov * PESO_PROVINCIA
          + match_tipo * PESO_TIPO
          + unicidad * PESO_UNICIDAD)


def clasificar_estado(score: float) -> str:
    """Asigna estado según umbrales calibrados."""
    if score >= UMBRAL_CONFIRMADO:
        return "CONFIRMADO_WEB"
    elif score >= UMBRAL_PROBABLE:
        return "PROBABLE_WEB"
    elif score >= UMBRAL_AMBIGUO:
        return "AMBIGUO_WEB"
    else:
        return "NO_ENCONTRADO_WEB"


# ─────────────────────────────────────────────────────────────────────────────
# FILTRO DE ELEGIBILIDAD
# ─────────────────────────────────────────────────────────────────────────────
def es_elegible(candidato: dict) -> tuple:
    """
    Determina si un candidato es elegible para enriquecimiento web.
    Retorna (bool, str_razon).
    """
    # 1. ¿Ya tiene RUC?
    ruc = candidato.get("ruc_final") or candidato.get("ruc_detectado_en_texto")
    if ruc and ruc != "SIN_DATO" and ruc != "None" and len(str(ruc)) > 5:
        return False, "YA_TIENE_RUC"
    
    # 2. ¿Razón social suficientemente clara?
    razon = candidato.get("razon_social_candidata", "")
    if not razon or len(razon.strip()) < 10:
        return False, "RAZON_SOCIAL_MUY_CORTA"
    
    # 3. ¿Es persona natural?
    tipo = candidato.get("candidato_original", {}).get("tipo_entidad_detectada", "")
    if not tipo:
        tipo = candidato.get("tipo_entidad_detectada", "")
    if tipo and normalizar(tipo) in ["PERSONA NATURAL", "PERSONA"]:
        return False, "ES_PERSONA_NATURAL"
    
    # 4. ¿Texto ilegible?
    estado = candidato.get("estado_resolucion", "")
    if estado == "TEXTO_ILEGIBLE":
        return False, "TEXTO_ILEGIBLE"
    
    return True, "ELEGIBLE"


# ─────────────────────────────────────────────────────────────────────────────
# ROUTER DE ESTRATEGIA
# ─────────────────────────────────────────────────────────────────────────────
def determinar_estrategia(tipo_entidad: str, tipo_es_debil: bool = False, modo: str = "REAL"):
    """
    Retorna la lista ordenada de adapters a consultar.
    Si el tipo es débil o dudoso, siempre incluye SRI como contraste.
    """
    tipo_norm = normalizar(tipo_entidad) if tipo_entidad else ""
    
    adapters = []
    
    if any(t in tipo_norm for t in ["COOPERATIVA", "COOP"]):
        adapters.append(SepsWebAdapter(modo=modo))
        if tipo_es_debil:
            adapters.append(SriWebAdapter(modo=modo))  # Contraste obligatorio
        else:
            adapters.append(SriWebAdapter(modo=modo))  # Fallback
    elif any(t in tipo_norm for t in ["COMPANIA", "CIA", "SA", "CA", "LTDA"]):
        adapters.append(SuperciasWebAdapter(modo=modo))
        if tipo_es_debil:
            adapters.append(SriWebAdapter(modo=modo))  # Contraste obligatorio
        else:
            adapters.append(SriWebAdapter(modo=modo))  # Fallback
    else:
        adapters.append(SriWebAdapter(modo=modo))  # Única fuente genérica
    
    return adapters


def tipo_es_debil(candidato: dict) -> bool:
    """Evalúa si el tipo de entidad es suficientemente confiable."""
    tipo = candidato.get("candidato_original", {}).get("tipo_entidad_detectada", "")
    if not tipo:
        tipo = candidato.get("tipo_entidad_detectada", "")
    
    tipos_debiles = {"DESCONOCIDO", "OTRO", "ENTIDAD", "ORGANIZACION", ""}
    return normalizar(tipo) in {normalizar(t) for t in tipos_debiles}


# ─────────────────────────────────────────────────────────────────────────────
# MOTOR PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────
def enriquecer_candidato(candidato: dict, modo: str = "REAL") -> dict:
    """
    Intenta enriquecer un candidato individual consultando adapters web.
    Retorna un registro de enriquecimiento con score y estado.
    """
    razon_social_original = candidato.get("razon_social_candidata", "")
    razon_social = limpiar_razon_social(razon_social_original)
    
    # Extraer provincia y tipo del candidato
    cand_orig = candidato.get("candidato_original", {})
    provincia_pdf = cand_orig.get("provincia_mencionada", "SIN_DATO")
    tipo_entidad = cand_orig.get("tipo_entidad_detectada", "DESCONOCIDO")
    
    # Determinar estrategia de búsqueda
    es_debil = tipo_es_debil(candidato)
    adapters = determinar_estrategia(tipo_entidad, es_debil, modo)
    
    mejor_resultado = None
    mejor_score = 0.0
    mejor_detalles = {}
    adapter_usado = "NINGUNO"
    todos_resultados = []
    
    # 2. Consultar adapters
    for adapter in adapters:
        resultados = adapter.search(razon_social, provincia_pdf, tipo_entidad)
        
        if not resultados:
            continue
        
        todos_resultados.extend(resultados)
        
        # Evaluar cada resultado de este adapter
        for resultado in resultados:
            sim_nombre = similitud_levenshtein(razon_social, resultado["razon_social"])
            match_prov = calcular_score_provincia(provincia_pdf, resultado.get("provincia"))
            match_tipo = calcular_score_tipo(tipo_entidad, adapter.FUENTE)
            unicidad = calcular_score_unicidad(len(resultados))
            
            score = calcular_score_total(sim_nombre, match_prov, match_tipo, unicidad)
            
            if score > mejor_score:
                mejor_score = score
                mejor_resultado = resultado
                adapter_usado = adapter.FUENTE
                mejor_detalles = {
                    "similitud_nombre": round(sim_nombre, 4),
                    "match_provincia": round(match_prov, 4),
                    "match_tipo_entidad": round(match_tipo, 4),
                    "unicidad_resultado": round(unicidad, 4)
                }

        # Si ya encontramos CONFIRMADO en el adapter primario, no seguir con fallback
        if mejor_score >= UMBRAL_CONFIRMADO:
            break

    # IMPORTANTE: Cerrar conexiones de adapters
    for adapter in adapters:
        if hasattr(adapter, 'close'):
            adapter.close()
    
    # Clasificar estado
    estado_web = clasificar_estado(mejor_score) if mejor_resultado else "NO_ENCONTRADO_WEB"
    
    # REGLA CRÍTICA: nunca CONFIRMADO si similitud_nombre < 0.85
    if estado_web == "CONFIRMADO_WEB" and mejor_detalles.get("similitud_nombre", 0) < 0.85:
        estado_web = "PROBABLE_WEB"
    
    return {
        "lote": candidato.get("lote", "DESCONOCIDO"),
        "razon_social_pdf": razon_social,
        "razon_social_pdf_original": razon_social_original,
        "razon_social_web": mejor_resultado["razon_social"] if mejor_resultado else None,
        "ruc_encontrado": mejor_resultado["ruc"] if mejor_resultado else None,
        "fuente": adapter_usado,
        "score_confianza": round(mejor_score, 4),
        "estado_web": estado_web,
        "modo_validacion": modo,
        "detalles_scoring": mejor_detalles,
        "provincia_pdf": provincia_pdf,
        "provincia_web": mejor_resultado.get("provincia") if mejor_resultado else None,
        "tipo_entidad": tipo_entidad,
        "adapter_usado": adapter_usado,
        "total_resultados_encontrados": len(todos_resultados),
        "timestamp_consulta": datetime.now().isoformat()
    }


# ─────────────────────────────────────────────────────────────────────────────
# EJECUCIÓN PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────
def ejecutar_enriquecimiento(input_paths: list, output_dir: str, modo: str = "REAL"):
    """Ejecuta el ciclo completo de enriquecimiento web para un lote."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # Leer todos los candidatos de los archivos de entrada
    candidatos = []
    lote_base = "DESCONOCIDO"
    
    for input_path in input_paths:
        p = Path(input_path)
        if not p.exists():
            print(f"[!] Archivo no encontrado, omitido: {p.name}")
            continue
        
        # Derivar nombre del lote
        name = p.name
        for prefix in ["manual_review_", "not_ready_for_master_", "resolved_"]:
            if name.startswith(prefix):
                lote_base = name.replace(prefix, "").replace(".jsonl", "")
                break
        
        with open(p, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    candidatos.append(json.loads(line))
    
    if not candidatos:
        print("[X] No se encontraron candidatos para enriquecer.")
        # Escribir archivos vacíos para evitar errores de dependencias de la cascada
        enriched_path = out_dir / f"web_enriched_{lote_base}.jsonl"
        with open(enriched_path, 'w', encoding='utf-8') as f:
            pass
        reporte = {
            "lote": lote_base,
            "timestamp": datetime.now().isoformat(),
            "modo": modo,
            "total_candidatos_recibidos": 0,
            "elegibles_para_busqueda": 0,
            "descartados": 0,
            "resultados": {},
            "archivos_generados": {
                "enriched": enriched_path.name
            }
        }
        report_path = out_dir / f"web_enrichment_report_{lote_base}.json"
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(reporte, f, ensure_ascii=False, indent=2)
        return
    
    # Filtrar elegibles
    elegibles = []
    descartados = []
    
    for c in candidatos:
        ok, razon = es_elegible(c)
        if ok:
            elegibles.append(c)
        else:
            descartados.append({"razon_social": c.get("razon_social_candidata", "?"), "razon_descarte": razon})
    
    print(f"\n[*] Iniciando Web Enrichment Layer (Paso 7B) — Modo: {modo}")
    print(f"    Candidatos recibidos  : {len(candidatos)}")
    print(f"    Elegibles para búsqueda: {len(elegibles)}")
    print(f"    Descartados           : {len(descartados)}")
    
    # Enriquecer cada candidato elegible
    resultados = []
    conteo_estados = {
        "CONFIRMADO_WEB": 0,
        "PROBABLE_WEB": 0,
        "AMBIGUO_WEB": 0,
        "NO_ENCONTRADO_WEB": 0
    }
    
    for i, c in enumerate(elegibles, 1):
        nombre = c.get("razon_social_candidata", "???")
        print(f"  -> [{i}/{len(elegibles)}] Buscando: {nombre[:60]}...", end=" ")
        
        resultado = enriquecer_candidato(c, modo)
        resultados.append(resultado)
        
        estado = resultado["estado_web"]
        conteo_estados[estado] = conteo_estados.get(estado, 0) + 1
        
        if resultado["ruc_encontrado"]:
            print(f"[{estado} | RUC: {resultado['ruc_encontrado']} | Score: {resultado['score_confianza']}]")
        else:
            print(f"[{estado}]")
    
    # Escribir resultados
    enriched_path = out_dir / f"web_enriched_{lote_base}.jsonl"
    with open(enriched_path, 'w', encoding='utf-8') as f:
        for r in resultados:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    
    # Escribir reporte
    reporte = {
        "lote": lote_base,
        "timestamp": datetime.now().isoformat(),
        "modo": modo,
        "total_candidatos_recibidos": len(candidatos),
        "elegibles_para_busqueda": len(elegibles),
        "descartados": len(descartados),
        "detalle_descartados": descartados[:20],  # Máximo 20 para no inflar
        "resultados": conteo_estados,
        "archivos_generados": {
            "enriched": enriched_path.name
        }
    }
    
    report_path = out_dir / f"web_enrichment_report_{lote_base}.json"
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(reporte, f, ensure_ascii=False, indent=2)
    
    # Resumen en consola
    print(f"\n=========================================")
    print(f" WEB ENRICHMENT LAYER (PASO 7B)")
    print(f"=========================================")
    print(f" Lote               : {lote_base}")
    print(f" Modo                : {modo}")
    print(f" Elegibles buscados  : {len(elegibles)}")
    print(f"-----------------------------------------")
    print(f"  CONFIRMADO_WEB     : {conteo_estados.get('CONFIRMADO_WEB', 0)}")
    print(f"  PROBABLE_WEB       : {conteo_estados.get('PROBABLE_WEB', 0)}")
    print(f"  AMBIGUO_WEB        : {conteo_estados.get('AMBIGUO_WEB', 0)}")
    print(f"  NO_ENCONTRADO_WEB  : {conteo_estados.get('NO_ENCONTRADO_WEB', 0)}")
    print(f"-----------------------------------------")
    print(f"[*] Resultados : {enriched_path.name}")
    print(f"[*] Reporte    : {report_path.name}")
    print(f"=========================================")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Paso 7B: Web Enrichment Layer — enriquecimiento de entidades sin RUC")
    parser.add_argument("--input_paths", nargs='+', required=True, 
                        help="Rutas a manual_review y/o not_ready_for_master JSONL")
    parser.add_argument("--output_dir", required=True, help="Carpeta de salida")
    parser.add_argument("--mode", default="MOCK", choices=["MOCK", "REAL"],
                        help="Modo de operación (MOCK = simulado, REAL = conexión externa)")
    
    args = parser.parse_args()
    ejecutar_enriquecimiento(args.input_paths, args.output_dir, args.mode)
