"""
=============================================================================
 PASO 7.5B — COMPUERTA DE CALIDAD PARA WEB ENRICHMENT
=============================================================================
 Evalúa la salida de 7B_web_enrichment.py y clasifica qué resultados web
 son suficientemente fuertes para reauditoría futura, y cuáles no.
 
 Reglas de promoción:
   CONFIRMADO_WEB  → LISTO_PARA_REAUDITORIA
   PROBABLE_WEB    → REQUIERE_REVISION
   AMBIGUO_WEB     → REQUIERE_REVISION
   NO_ENCONTRADO   → SIN_RESULTADO
 
 ESTE PASO NO ENVÍA NADA AL MAESTRO.
=============================================================================
"""
import json
import argparse
from pathlib import Path
from datetime import datetime
from collections import Counter


# ─────────────────────────────────────────────────────────────────────────────
# REGLAS DE PROMOCIÓN
# ─────────────────────────────────────────────────────────────────────────────
REGLAS_PROMOCION = {
    "CONFIRMADO_WEB":     "LISTO_PARA_REAUDITORIA",
    "PROBABLE_WEB":       "REQUIERE_REVISION",
    "AMBIGUO_WEB":        "REQUIERE_REVISION",
    "NO_ENCONTRADO_WEB":  "SIN_RESULTADO"
}

# Un registro es "apto para reauditoría" solo con estos estados
ESTADOS_APTOS = {"LISTO_PARA_REAUDITORIA"}

# Un registro requiere intervención humana con estos
ESTADOS_REVISION = {"REQUIERE_REVISION"}


# ─────────────────────────────────────────────────────────────────────────────
# DEDUPLICACIÓN
# ─────────────────────────────────────────────────────────────────────────────
def deduplicar_registros(registros: list) -> tuple:
    """
    Detecta y elimina duplicados por razón social + lote.
    Si hay duplicados, conserva el que tenga MAYOR score de confianza.
    
    Retorna: (registros_unicos, duplicados_eliminados)
    """
    vistos = {}  # key: (razon_social_normalizada, lote) -> mejor registro
    duplicados = []
    
    for r in registros:
        clave = (r.get("razon_social_pdf", "").upper().strip(), r.get("lote", ""))
        score = r.get("score_confianza", 0.0)
        
        if clave in vistos:
            existente_score = vistos[clave].get("score_confianza", 0.0)
            if score > existente_score:
                # El nuevo es mejor, el viejo se va a duplicados
                duplicados.append(vistos[clave])
                vistos[clave] = r
            else:
                duplicados.append(r)
        else:
            vistos[clave] = r
    
    return list(vistos.values()), duplicados


# ─────────────────────────────────────────────────────────────────────────────
# EVALUACIÓN PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────
def evaluar_web_enrichment(enriched_path: str, output_dir: str):
    """Evalúa la salida del web enrichment y genera clasificación."""
    enriched_file = Path(enriched_path)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    if not enriched_file.exists():
        print(f"[X] Archivo no encontrado: {enriched_file}")
        return
    
    # Derivar lote
    lote_base = enriched_file.name.replace("web_enriched_", "").replace(".jsonl", "")
    
    # Leer registros
    registros_brutos = []
    with open(enriched_file, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                registros_brutos.append(json.loads(line))
    
    if not registros_brutos:
        print(f"[X] Archivo vacío: {enriched_file.name}")
        ready_path = out_dir / f"web_ready_for_reaudit_{lote_base}.jsonl"
        not_ready_path = out_dir / f"web_not_ready_{lote_base}.jsonl"
        report_path = out_dir / f"web_enrichment_audit_report_{lote_base}.json"
        
        with open(ready_path, 'w', encoding='utf-8') as f:
            pass
        with open(not_ready_path, 'w', encoding='utf-8') as f:
            pass
            
        reporte = {
            "lote": lote_base,
            "timestamp": datetime.now().isoformat(),
            "paso": "7.5B",
            "metricas_entrada": {
                "registros_brutos": 0,
                "duplicados_eliminados": 0,
                "registros_unicos_evaluados": 0
            },
            "distribucion_estado_web_original": {},
            "distribucion_estado_compuerta": {},
            "resumen_salida": {
                "aptos_para_reauditoria": 0,
                "requieren_revision": 0,
                "sin_resultado": 0
            },
            "archivos_generados": {
                "web_ready_for_reaudit": ready_path.name,
                "web_not_ready": not_ready_path.name
            }
        }
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(reporte, f, ensure_ascii=False, indent=2)
            
        return
    
    # ── Fase 1: Deduplicación ──────────────────────────────────────────
    registros, duplicados = deduplicar_registros(registros_brutos)
    
    print(f"\n[*] Iniciando Compuerta de Calidad Web (Paso 7.5B)")
    print(f"    Lote                  : {lote_base}")
    print(f"    Registros brutos      : {len(registros_brutos)}")
    print(f"    Duplicados detectados : {len(duplicados)}")
    print(f"    Registros únicos      : {len(registros)}")
    
    # ── Fase 2: Clasificación ──────────────────────────────────────────
    aptos = []        # LISTO_PARA_REAUDITORIA
    revision = []     # REQUIERE_REVISION (PROBABLE + AMBIGUO)
    sin_resultado = [] # SIN_RESULTADO
    
    conteo_original = Counter()
    conteo_promocion = Counter()
    
    for reg in registros:
        estado_web = reg.get("estado_web", "NO_ENCONTRADO_WEB")
        estado_promocion = REGLAS_PROMOCION.get(estado_web, "SIN_RESULTADO")
        
        conteo_original[estado_web] += 1
        conteo_promocion[estado_promocion] += 1
        
        # Enriquecer registro con estado de compuerta
        reg["estado_compuerta_7_5B"] = estado_promocion
        reg["evaluado_por"] = "7_5B_evaluate_web_enrichment"
        reg["timestamp_evaluacion"] = datetime.now().isoformat()
        
        # Validación adicional de seguridad
        if estado_promocion == "LISTO_PARA_REAUDITORIA":
            # Doble check: ¿realmente tiene un RUC y score alto?
            if not reg.get("ruc_encontrado") or reg.get("score_confianza", 0) < 0.90:
                estado_promocion = "REQUIERE_REVISION"
                reg["estado_compuerta_7_5B"] = estado_promocion
                reg["observacion_compuerta"] = "Degradado de CONFIRMADO a REVISION: RUC ausente o score insuficiente."
                conteo_promocion["LISTO_PARA_REAUDITORIA"] -= 1
                conteo_promocion["REQUIERE_REVISION"] += 1
        
        # Clasificar en bandeja correspondiente
        if estado_promocion in ESTADOS_APTOS:
            aptos.append(reg)
        elif estado_promocion in ESTADOS_REVISION:
            revision.append(reg)
        else:
            sin_resultado.append(reg)
    
    # ── Fase 3: Escritura de archivos ─────────────────────────────────
    ready_path = out_dir / f"web_ready_for_reaudit_{lote_base}.jsonl"
    not_ready_path = out_dir / f"web_not_ready_{lote_base}.jsonl"
    report_path = out_dir / f"web_enrichment_audit_report_{lote_base}.json"
    
    # Aptos para reauditoría
    with open(ready_path, 'w', encoding='utf-8') as f:
        for r in aptos:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    
    # No aptos (revisión + sin resultado)
    with open(not_ready_path, 'w', encoding='utf-8') as f:
        for r in (revision + sin_resultado):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    
    # Reporte analítico
    reporte = {
        "lote": lote_base,
        "timestamp": datetime.now().isoformat(),
        "paso": "7.5B",
        "metricas_entrada": {
            "registros_brutos": len(registros_brutos),
            "duplicados_eliminados": len(duplicados),
            "registros_unicos_evaluados": len(registros)
        },
        "distribucion_estado_web_original": dict(conteo_original),
        "distribucion_estado_compuerta": dict(conteo_promocion),
        "resumen_salida": {
            "aptos_para_reauditoria": len(aptos),
            "requieren_revision": len(revision),
            "sin_resultado": len(sin_resultado)
        },
        "archivos_generados": {
            "web_ready_for_reaudit": ready_path.name,
            "web_not_ready": not_ready_path.name
        },
        "duplicados_muestra": [
            {
                "razon_social": d.get("razon_social_pdf", "?"),
                "score": d.get("score_confianza", 0),
                "estado_web": d.get("estado_web", "?")
            }
            for d in duplicados[:10]  # Máximo 10 para no inflar
        ]
    }
    
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(reporte, f, ensure_ascii=False, indent=2)
    
    # ── Fase 4: Resumen en consola ────────────────────────────────────
    print(f"\n=========================================")
    print(f" COMPUERTA DE CALIDAD WEB (PASO 7.5B)")
    print(f"=========================================")
    print(f" Lote                : {lote_base}")
    print(f" Registros evaluados : {len(registros)} (de {len(registros_brutos)} brutos)")
    print(f" Duplicados purgados : {len(duplicados)}")
    print(f"-----------------------------------------")
    print(f" Estados web originales:")
    for estado, n in sorted(conteo_original.items()):
        print(f"   {estado:25s}: {n}")
    print(f"-----------------------------------------")
    print(f" Clasificación final de compuerta:")
    print(f"   LISTO_PARA_REAUDITORIA : {len(aptos)}")
    print(f"   REQUIERE_REVISION      : {len(revision)}")
    print(f"   SIN_RESULTADO          : {len(sin_resultado)}")
    print(f"-----------------------------------------")
    print(f"[*] Aptos     : {ready_path.name}")
    print(f"[*] No aptos  : {not_ready_path.name}")
    print(f"[*] Reporte   : {report_path.name}")
    print(f"=========================================")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Paso 7.5B: Compuerta de calidad para resultados de Web Enrichment"
    )
    parser.add_argument("--enriched_path", required=True,
                        help="Ruta al archivo web_enriched_[lote].jsonl generado por el Paso 7B")
    parser.add_argument("--output_dir", required=True,
                        help="Carpeta de salida")
    
    args = parser.parse_args()
    evaluar_web_enrichment(args.enriched_path, args.output_dir)
