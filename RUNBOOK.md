# LECTOR PDF — Pipeline ETL de Documentos Corporativos
## Runbook de Operación v1.1.0

---

## 1. Objetivo General

Este sistema extrae, normaliza, enriquece y consolida **información empresarial** (razón social, RUC, provincia, tipo de entidad) desde archivos PDF contenidos en lotes ZIP.

El pipeline transforma documentos no estructurados en un **repositorio maestro SQLite** consultable, auditado y con trazabilidad completa desde el PDF de origen hasta el registro final.

**No es un OCR genérico.** Es un sistema de inteligencia documental diseñado para identificar entidades corporativas ecuatorianas dentro de documentos institucionales (oficios IESS, resoluciones SEPS, etc.).

---

## 2. Estructura de Carpetas

```
LECTOR PDF/
│
├── data/
│   ├── input/                  ← ZIPs de entrada (LOTE 1.zip, etc.)
│   ├── temp/                   ← Archivos temporales de descompresión
│   │   └── LOTE 1/             ← PDFs extraídos + inventory.json
│   ├── output/                 ← Todos los artefactos de cada corrida
│   │   ├── consolidated_*.jsonl
│   │   ├── entities_extracted_*.jsonl
│   │   ├── candidates_*.jsonl
│   │   ├── resolved_*.jsonl
│   │   ├── ready_for_master_*.jsonl
│   │   ├── not_ready_for_master_*.jsonl
│   │   ├── manual_review_*.jsonl
│   │   ├── web_enriched_*.jsonl          ← Solo si web enrichment activo
│   │   ├── web_ready_for_reaudit_*.jsonl ← Solo si web enrichment activo
│   │   ├── web_not_ready_*.jsonl         ← Solo si web enrichment activo
│   │   ├── resultado_final_*.xlsx        ← Reporte Excel para usuario
│   │   ├── resultado_final_*.json        ← Reporte JSON analítico
│   │   └── pipeline_run_report_*.json    ← Bitácora de la corrida
│   ├── master/
│   │   └── master_entities.sqlite        ← Base de datos maestra
│   └── external/
│       └── dataset_local.sqlite          ← Dataset local de referencia (RUCs conocidos)
│
├── scripts/
│   ├── process_batch.py                  ← Orquestador principal
│   ├── 1_unzip_and_inventory.py
│   ├── 2_extract_text.py
│   ├── 3_consolidate_batch.py
│   ├── 4_extract_entities.py
│   ├── 5_deduplicate_entities.py
│   ├── 7_resolve_candidates.py
│   ├── 7_5_evaluate_resolution.py
│   ├── 7B_web_enrichment.py              ← Opcional
│   ├── 7_5B_evaluate_web_enrichment.py   ← Opcional
│   ├── 8_master_merger.py
│   ├── 9_export_business_results.py
│   └── adapters/
│       ├── base.py              ← Interfaz de resolución (Paso 7)
│       ├── dataset.py           ← Adapter dataset local
│       ├── router.py            ← Enrutador de adapters
│       ├── mock.py              ← Adapter dummy
│       ├── seps.py / supercias.py  ← Stubs (Paso 7)
│       ├── web_base.py          ← Interfaz web (Paso 7B)
│       ├── seps_web.py          ← Adapter SEPS mock (7B)
│       ├── supercias_web.py     ← Adapter Supercias mock (7B)
│       └── sri_web.py           ← Adapter SRI mock (7B)
│
└── requirements.txt
```

---

## 3. Descripción de Cada Paso

### Pipeline Principal (obligatorio)

| Paso | Script | Entrada | Salida | Qué Hace |
|------|--------|---------|--------|----------|
| **1** | `1_unzip_and_inventory.py` | ZIP | `inventory.json` + PDFs extraídos | Descomprime con protección Zip Slip, genera UUID por archivo, calcula hashes SHA-256 |
| **2** | `2_extract_text.py` | `inventory.json` | JSONL por PDF (1 línea por página) | Extrae texto página por página con PyMuPDF. Marca páginas sin texto o con error |
| **3** | `3_consolidate_batch.py` | `inventory.json` | `consolidated_[lote].jsonl` | Fusiona todos los JSONL individuales en un solo archivo maestro del lote con validación |
| **4** | `4_extract_entities.py` | `consolidated` | `entities_extracted_[lote].jsonl` | Envía cada página a GPT-4o-mini para detectar entidades empresariales. Regla de Cero Alucinación |
| **5** | `5_deduplicate_entities.py` | `entities_extracted` | `candidates_[lote].jsonl` | Normaliza razones sociales, agrupa menciones idénticas, genera candidatos únicos |
| **7** | `7_resolve_candidates.py` | `candidates` | `resolved_[lote].jsonl` + `manual_review` | Motor de resolución inteligente: busca RUC en dataset local, marca no encontrados para revisión |
| **7.5** | `7_5_evaluate_resolution.py` | `resolved` | `ready_for_master` + `not_ready_for_master` | Esclusa de cuarentena: solo entidades con RUC confirmado pasan. El resto queda bloqueado |
| **8** | `8_master_merger.py` | `ready_for_master` | Escritura en `master_entities.sqlite` | Inserta/actualiza en el repositorio maestro con idempotencia y rollback transaccional |
| **9** | `9_export_business_results.py` | `resolved` | `resultado_final_[lote].xlsx` + `.json` | Genera Excel profesional con colores, bordes y columnas legibles para el usuario final |

### Pipeline Opcional (Web Enrichment)

| Paso | Script | Entrada | Salida | Qué Hace |
|------|--------|---------|--------|----------|
| **7B** | `7B_web_enrichment.py` | `manual_review` + `not_ready_for_master` | `web_enriched_[lote].jsonl` | Busca RUC faltantes en fuentes web (SEPS, Supercias, SRI). Actualmente en modo MOCK |
| **7.5B** | `7_5B_evaluate_web_enrichment.py` | `web_enriched` | `web_ready_for_reaudit` + `web_not_ready` | Clasifica resultados web: LISTO_PARA_REAUDITORIA, REQUIERE_REVISION, SIN_RESULTADO |

---

## 4. Comandos Principales

### Corrida Normal Completa (un lote)
```powershell
python scripts/process_batch.py `
  --zip_path "data/input/LOTE 1.zip" `
  --master_db "data/master/master_entities.sqlite" `
  --output_dir "data/output"
```

### Con Web Enrichment
```powershell
python scripts/process_batch.py `
  --zip_path "data/input/LOTE 1.zip" `
  --master_db "data/master/master_entities.sqlite" `
  --output_dir "data/output" `
  --enable_web_enrichment
```

### Simulación (no ejecuta nada)
```powershell
python scripts/process_batch.py `
  --zip_path "data/input/LOTE 1.zip" `
  --master_db "data/master/master_entities.sqlite" `
  --output_dir "data/output" `
  --dry_run
```

### Reanudar desde un paso
```powershell
python scripts/process_batch.py `
  --zip_path "data/input/LOTE 1.zip" `
  --master_db "data/master/master_entities.sqlite" `
  --output_dir "data/output" `
  --resume_from_step 7.5
```

### Reprocesar un lote en el maestro
```powershell
python scripts/process_batch.py `
  --zip_path "data/input/LOTE 1.zip" `
  --master_db "data/master/master_entities.sqlite" `
  --output_dir "data/output" `
  --resume_from_step 8 `
  --force_reprocess_master
```

---

## 5. Cuándo Usar Cada Flag

### `--dry_run`
**Cuándo:** Antes de procesar un lote nuevo por primera vez.
- Muestra qué pasos se ejecutarían sin tocar nada.
- Valida que los prerequisitos existan.
- Los pasos quedan marcados como `SIMULADO`.

### `--resume_from_step [ID]`
**Cuándo:** Un paso falló y quieres continuar sin rehacer todo.
- Salta los pasos anteriores al ID indicado.
- Valida que las dependencias del paso de reanudación existan antes de continuar.
- Ejemplo: si el Paso 4 (LLM) falló por timeout de API, corriges y reanudas con `--resume_from_step 4`.

### `--force_reprocess_master`
**Cuándo:** Necesitas reinyectar un lote en el maestro (por corrección de datos o recalibración).
- Revierte el impacto previo del lote antes de reinyectar.
- Las métricas (total_menciones, total_lotes_detectado) se recalculan limpiamente.
- **Riesgo:** Si hay cambios en pasos anteriores, asegúrate de regenerar `ready_for_master` primero.

### `--enable_web_enrichment`
**Cuándo:** Quieres intentar resolver RUCs faltantes mediante búsquedas web.
- Activa los pasos 7B y 7.5B después del 7.5.
- Los resultados **nunca** entran al maestro automáticamente.
- Genera archivos consultivos para revisión manual.
- Actualmente opera en modo MOCK (sin conexión real a APIs gubernamentales).

### `--skip_steps [ID ...]`
**Cuándo:** Quieres excluir pasos específicos.
- Ejemplo: `--skip_steps 9` para omitir la exportación Excel.

### `--no_stop_on_error`
**Cuándo:** Quieres que el pipeline siga aunque un paso crítico falle.
- Por defecto, el pipeline aborta en el primer error.

---

## 6. Qué Revisar Después de Cada Corrida

### Verificación rápida (30 segundos)
1. **`pipeline_run_report_[lote].json`** — ¿Todos los pasos en OK?
2. **`resultado_final_[lote].xlsx`** — Abrir en Excel, verificar filas y colores.

### Verificación detallada (5 minutos)
| Archivo | Qué Buscar |
|---------|------------|
| `pipeline_run_report_[lote].json` | Estado de cada paso. Buscar cualquier `ERROR` |
| `entity_extraction_report_[lote].json` | Cuántas entidades detectó el LLM. Si es 0, el PDF puede ser irrelevante |
| `ready_for_master_[lote].jsonl` | Entidades que entraron al maestro. Verificar que los RUCs sean plausibles |
| `not_ready_for_master_[lote].jsonl` | Entidades rechazadas. Revisar si hay falsos rechazos |
| `manual_review_[lote].jsonl` | Entidades sin resolver. Volumen esperado: 50-70% según calidad de los PDFs |
| `resultado_final_[lote].xlsx` | Filas verdes = resueltas. Filas amarillas = pendientes |

### Si web enrichment está activo
| Archivo | Qué Buscar |
|---------|------------|
| `web_enrichment_report_[lote].json` | Cuántos CONFIRMADO, PROBABLE, AMBIGUO |
| `web_ready_for_reaudit_[lote].jsonl` | ¿Hay candidatos promovibles? Si es 0, el mock no tiene datos relevantes |

---

## 7. Qué Entra al Maestro y Qué No

### SÍ entra al maestro (vía Paso 8)
- Entidades con RUC **confirmado desde el PDF** (extraído del texto)
- Entidades con RUC **confirmado por dataset local** (coincidencia exacta)

### NO entra al maestro
- Entidades sin RUC
- Entidades con coincidencia parcial o ambigua en el dataset
- Entidades marcadas para revisión manual
- Resultados del web enrichment (7B / 7.5B) — **NUNCA**
- Entidades con tipo "PERSONA_NATURAL"
- Entidades con texto ilegible

### Flujo de promoción
```
PDF → LLM → Candidato → Resolución → Auditoría → Maestro
                                         │
                                         ├── ready_for_master ──→ Paso 8 ──→ SQLite ✅
                                         │
                                         ├── not_ready ──→ BLOQUEADO ❌
                                         │
                                         └── manual_review ──→ BLOQUEADO ❌
                                                   │
                                                   └──→ [7B Web Enrichment] ──→ Consultivo solo
```

---

## 8. Riesgos y Advertencias

### 🔴 Críticos

| Riesgo | Impacto | Mitigación |
|--------|---------|------------|
| Correr el mismo lote dos veces sin `--force_reprocess` | Evidencias duplicadas en el maestro | El Paso 8 detecta lotes previos y aborta. Usar `--force_reprocess_master` para reinyectar |
| Modificar `ready_for_master` manualmente | Datos corruptos en el maestro | Nunca editar archivos intermedios. Siempre regenerar desde el paso correspondiente |
| Perder la variable `OPENAI_API_KEY` | Paso 4 falla silenciosamente | Configurarla como variable de entorno antes de ejecutar |

### 🟡 Operacionales

| Riesgo | Impacto | Mitigación |
|--------|---------|------------|
| PDFs sin texto (escaneados) | PyMuPDF extrae texto vacío, el LLM no encuentra entidades | Revisar `text_extraction_report`. Considerar OCR previo |
| PDFs con nombres de archivo con caracteres especiales | Posibles errores de path en Windows | El paso 1 usa UUIDs internos, pero los nombres originales se preservan en el inventario |
| Web enrichment en modo MOCK | Los resultados no reflejan datos reales | No tomar decisions basadas en resultados MOCK. Son solo para validar la arquitectura |
| Dataset local desactualizado | Menos RUCs resueltos por la vía local | Actualizar `data/external/dataset_local.sqlite` periódicamente |

### 🟢 Informativos

| Nota | Detalle |
|------|---------|
| El paso 6 existe como script pero no está integrado al orquestador | Era un placeholder para validación externa. Su funcionalidad fue absorbida por 7 + 7.5 |
| El web enrichment genera duplicados internos | 7.5B los purga automáticamente. Es comportamiento esperado por leer 2 archivos con solapamiento |
| Los umbrales de scoring web (0.90/0.75/0.55) son calibrados | No modificarlos sin repetir el ciclo de diagnóstico documentado |

---

## 9. Flujo Recomendado para Operación Normal

### Primera vez con un lote nuevo

```
1. Colocar el ZIP en data/input/
2. Ejecutar con --dry_run para validar
3. Ejecutar sin flags para corrida completa
4. Revisar pipeline_run_report → ¿Todos OK?
5. Abrir resultado_final_[lote].xlsx → ¿Los datos tienen sentido?
6. Verificar manual_review_[lote].jsonl → ¿Es razonable el volumen pendiente?
```

### Reprocesar un lote (corregido)

```
1. Identificar desde qué paso necesitas rehacer
2. Ejecutar con --resume_from_step [paso] --force_reprocess_master
3. Verificar que las métricas del maestro quedaron consistentes
```

### Explorar web enrichment (experimental)

```
1. Ejecutar con --enable_web_enrichment
2. Revisar web_enrichment_audit_report → ¿Hay CONFIRMADO_WEB o PROBABLE_WEB?
3. NO tomar acción sobre el maestro basándose en resultados MOCK
4. Cuando los adapters estén conectados a APIs reales, repetir el ciclo de calibración
```

### Producción multi-lote

```
Para cada ZIP en data/input/:
  1. Ejecutar process_batch.py con ese ZIP
  2. Verificar reporte
  3. Continuar con el siguiente

El maestro se acumula progresivamente.
Cada lote queda registrado en la tabla processed_batches.
```

---

## Dependencias

```
pip install PyMuPDF openai pandas openpyxl
```

| Paquete | Versión Mínima | Usado En |
|---------|---------------|----------|
| `PyMuPDF` | 1.25.3 | Paso 2 (extracción de texto) |
| `openai` | 1.0.0 | Paso 4 (extracción semántica con LLM) |
| `pandas` | 2.0+ | Paso 9 (generación de Excel) |
| `openpyxl` | 3.1+ | Paso 9 (estilos de Excel) |
| `sqlite3` | nativo | Pasos 7, 8 (dataset local y maestro) |

Variable de entorno requerida:
```
OPENAI_API_KEY=sk-...
```

---

*Documento generado: 2026-03-27 — Pipeline v1.1.0*

---

## 10. Modo Agente (`agent/`)

Un agente conductor (Claude Agent SDK) corre el pipeline y delega cada entidad **sin RUC** a un subagente
`investigador` que busca en internet (WebSearch/WebFetch) hasta encontrarla o agotar ≥8 estrategias.

```powershell
python agent/lector_agent.py --zip "masiva_21.zip" --limite 5     # pipeline + investigar hasta 5 pendientes
python agent/lector_agent.py --investigar --limite 10             # solo investigar lo ya pendiente
python agent/lector_agent.py --completar --campos ruc,estado_legal,direccion --limite 5
python agent/lector_agent.py --exportar                           # data/output/entidades_enriquecidas.xlsx
```

- Autenticación: sesión de Claude Code (`/login`) o `ANTHROPIC_API_KEY`. El Paso 4 sigue usando `OPENAI_API_KEY`.
- Todo hallazgo se guarda en `master_entities.sqlite` → `agent_findings` (valor + URL + cita textual + confianza),
  `agent_research_log` (cada intento) y `agent_entity_status`.
- **Cambio respecto a §7:** un RUC hallado en la web con confianza ALTA (fuente oficial o 2 fuentes independientes que
  coinciden en nombre+RUC) SÍ entra a `master_entities` con `estado_resolucion_master='RUC_WEB_AGENTE'` y
  `fuente_ruc='WEB_AGENTE:<url>'`. Confianza MEDIA/BAJA queda solo en `agent_findings`.
- El dígito verificador del RUC es informativo: 17 de los 37 RUC del maestro (extraídos de PDFs) no lo pasan.
- `LECTOR_MASTER_DB=<ruta>` apunta el agente a otra base (para pruebas sobre una copia).
