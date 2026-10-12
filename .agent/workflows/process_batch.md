---
description: Flujo predeterminado para procesar lotes de PDFs desde un archivo ZIP
---

# Pipeline Batch de Procesamiento PDF

Este documento define la operación estándar para la ingesta, validación, extracción de documentos y consolidación per-lote (MVP Fase 1).

## Paso 1: Recepción y Descompresión Segura
- **Entrada Esperada**: Un archivo `.zip` depositado en `data/input/`.
- **Acción Exacta**: Usar la skill `batch-unzipper`. El agente ejecutará en consola:
  `python scripts/1_unzip_and_inventory.py --zip_path "data/input/[nombre_lote_con_zip_o_sin_zip]" --temp_dir "data/temp"`
- **Salidas Esperadas**: 
  - Archivos PDF validados y ubicados en `data/temp/[lote_base]/...`
  - `inventory.json` (Listado de PDFs válidos, SHA256, UUID, etc).
  - `batch_report.json` (Métricas de la descompresión).
- **Criterio de Éxito**: Se crea el inventario y se cuenta con al menos >0 `total_pdfs_extraidos_ok`.
- **Criterio de Fallo**: El archivo ZIP está corrupto (BadZipFile) o `total_pdfs_extraidos_ok` es 0.

## Paso 2: Extracción de Texto Crudo (Página por Página)
- **Entrada Esperada**: Archivo `inventory.json` previamente generado en `data/temp/[lote_base]`.
- **Acción Exacta**: Usar la skill `pdf-text-extractor`. El agente ejecutará en consola:
  `python scripts/2_extract_text.py --inventory_path "data/temp/[lote_base]/inventory.json"`
- **Salidas Esperadas**: 
  - Archivos `.jsonl` concentrados en una subcarpeta dedicada `data/temp/[lote_base]/extracted_text/[id_documento].jsonl`. (La carpeta se limpia en cada ejecución de este paso para garantizar idempotencia).
  - Archivo maestro de auditoría tabular de extracción en `data/temp/[lote_base]/text_extraction_report.json`.
- **Criterio de Éxito**: Se crea el `text_extraction_report.json` y la carpeta `extracted_text/` cuenta con múltiples `.jsonl`.
- **Criterio de Fallo**: Ausencia de respuesta del script o falla total de lectura del PDF.

## Paso 3: Consolidación Batch y Trazabilidad Final
- **Entrada Esperada**: 
  - Archivo `inventory.json`.
  - Resultados alojados en la carpeta `data/temp/[lote_base]/extracted_text/`.
  - Reporte `text_extraction_report.json`.
- **Acción Exacta**: Usar la skill `batch-consolidator`. El agente ejecutará en consola:
  `python scripts/3_consolidate_batch.py --inventory_path "data/temp/[lote_base]/inventory.json" --output_dir "data/output"`
- **Salidas Esperadas**:
  - `data/output/consolidated_[lote_base].jsonl` reuniendo todo el texto bajo una misma matriz de estructura página por registro, desechando registros sin la estructura canónica.
  - `data/output/final_batch_report_[lote_base].json` resumiendo métricas en crudo y documentando inconsistencias entre el inventario y la extracción real.
- **Criterio de Fallo**: Ausencia del inventario o errores pánicos descritos por el script Python.

## Paso 4: Extracción Semántica de Entidades (Fase 2 MVP)
- **Entrada Esperada**: Archivo `data/output/consolidated_[lote_base].jsonl`.
- **Acción Exacta**: Usar la skill `entity-extractor`. El agente asegurará disponer de `OPENAI_API_KEY` en entorno y ejecutará:
  `python scripts/4_extract_entities.py --consolidated_path "data/output/consolidated_[lote_base].jsonl" --output_dir "data/output"`
- **Salidas Esperadas**:
  - `entities_extracted_[lote_base].jsonl` incorporando arreglos de entidades (o marcando SIN_ENTIDAD_CLARA), fusionados con los datos de trazabilidad (`lote`, `id_documento`, `pagina_pdf`, etc).
  - `entity_extraction_report_[lote_base].json` entregando conteo de inferencias.
- **Criterio de Éxito**: Desglose exitoso donde la cardinalidad de Entidades >= 1 para los registros legibles con confianza "DETECTADA" o "DUDOSA".
- **Criterio de Fallo**: Bloqueo por falta de variables de entorno de API, cuotas agotadas (429) o fallas de red constantes en la inyección de prompt al modelo.

## Paso 5: Purificación y Agrupación de Candidatos (Fase 2.5)
- **Entrada Esperada**: Archivo `data/output/entities_extracted_[lote_base].jsonl`.
- **Acción Exacta**: Usar la skill `entity-deduplicator`. El agente ejecutará:
  `python scripts/5_deduplicate_entities.py --entities_path "data/output/entities_extracted_[lote_base].jsonl" --output_dir "data/output"`
- **Salidas Esperadas**:
  - `candidates_[lote_base].jsonl` conteniendo empresas únicas con métricas de redundancia calculadas (`menciones_totales`).
  - `candidates_report_[lote_base].json` con un resumen operativo global.
- **Criterio de Éxito**: Agrupación finalizada con >0 registros evaluados como "LISTA_PARA_BUSQUEDA" o "REVISAR".
- **Criterio de Fallo**: Archivo jsonl estructurado de forma inesperada o ausente.

## Paso 7: Motor de Resolución y Decisión Semántica (Fase 3 - Diseño Enchufable)
- **Entrada Esperada**: Archivo `data/output/candidates_[lote_base].jsonl`.
- **Acción Exacta**: Correr la skill de orquestación de resolución que enruta la base entre reglas de certeza local, módulos de scraping remoto o derivación a humanos:
  `python scripts/7_resolve_candidates.py --candidates_path "data/output/candidates_[lote_base].jsonl" --output_dir "data/output" --adapter "mock"`
- **Salidas Esperadas**:
  - `resolved_[lote_base].jsonl` registrando toda resolución automática/enriquecida por API, junto a sus metadatos e inyectando un `adapter` externo para rellenar RUCs.
  - `manual_review_[lote_base].jsonl` sink/embudo diseñado para analistas humanos conteniendo "basura", "entidades únicas" o "casos con ambigüedad extrema".
  - `resolution_report_[lote_base].json`.
- **Criterio de Éxito**: Agrupación tripartita de rutas sin arrojar excepciones. (Nota: Deprecia conceptualmente el script transitorio 6_external_validation.py).
- **Criterio de Fallo**: Fallo de indexado de red (`import error`) sobre la estructura dinámica de adaptadores.

## Paso 9: Producción de Reportes Finales (Excel)
- **Entrada Esperada**: Archivos procesados en `data/output/resolved_[lote_base].jsonl` y `manual_review_[lote_base].jsonl`.
- **Acción Exacta**: Correr el orquestador de exportación final para la capa de negocio y analistas:
  `python scripts/9_export_business_results.py --resolved_path "data/output/resolved_[lote_base].jsonl" --output_dir "data/output" --mode "batch"`
- **Salidas Esperadas**:
  - `resultado_final_[lote_base].xlsx`: Hoja de cálculo principal, coloreada y estructurada para uso de la dirección.
  - `resultado_final_[lote_base].json`: Mismo contenido en un arreglo JSON puro.
- **Criterio de Éxito**: Despliegue del dataset tabulado y estéticamente formateado.
- **Criterio de Fallo**: Archivo de origen `resolved` no encontrado.
