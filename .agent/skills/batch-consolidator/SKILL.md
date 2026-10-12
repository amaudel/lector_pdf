---
name: batch-consolidator
description: Une múltiples resultados JSONL dispersos del paso 2 en un solo reporte unificado junto a su inventario, generando un manifiesto de corrida.
---

# Objetivo
Generar un único archivo maestro (`data/output/consolidated_[lote_base].jsonl`) de todos los documentos y páginas extraídas validando cruces estrictos contra el `inventory.json` base. Cada registro debe cumplir con una matriz de campos exigida. Adicionalmente, entregar el Manifiesto final sumario JSON (`final_batch_report_[lote_base].json`).

# Instrucciones
Cuando debas usar esta skill:
1. Asegúrate de conocer la ruta exacta al `inventory.json` del lote actual (por lo general `data/temp/[lote_base]/inventory.json`).
2. Ejecuta el comando en terminal:
   `python scripts/3_consolidate_batch.py --inventory_path "RUTA_AL_INVENTARIO_JSON" --output_dir "data/output"`
3. Verifica la salida en la terminal para confirmar que se lograron consolidar los registros, observa posibles registros inválidos, y cruza las inconsistencias detectadas (ej. FALTANTE o HUERFANO).
4. Confirma al usuario la disponibilidad de los resultados generados nativamente basados en el `lote_base` en `data/output/`.

# Restricciones
- No utilizar la skill si no se han completado los Pasos 1 y 2 correspondientes al `lote_base`.
- Este paso solo verifica e ingresa resultados (LOAD Data); NO extrae texto, NO usa LLM ni OCR, NO infiere RUCs ni entidades.
