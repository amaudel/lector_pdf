---
name: pdf-text-extractor
description: Lee el inventory.json generado en el paso 1 e itera sobre cada PDF extrayendo deterministamente el texto de cada página usando PyMuPDF.
---

# Objetivo
Generar una extracción de texto ruda (Raw Text) iterando sobre los archivos listados en un inventario, grabando el resultado como un `.jsonl` dentro de la subcarpeta `extracted_text/` de cada lote y generando un `text_extraction_report.json` con trazabilidad a nivel de página, sin aplicar LLM todavía.

# Instrucciones
Cuando debas usar esta skill:
1. Asegúrate de conocer la ruta exacta al `inventory.json` del lote actual (por lo general `data/temp/[lote]/inventory.json`).
2. Verifica que el archivo `requirements.txt` asegure tener instalado `PyMuPDF`.
3. Ejecuta el comando en terminal:
   `python scripts/2_extract_text.py --inventory_path "RUTA_AL_INVENTORY_JSON"`
4. Revisa las salidas en consola para asegurar que las páginas y documentos se han procesado satisfactoriamente.
5. Verifica la generación del archivo `data/temp/[lote]/text_extraction_report.json`.

# Restricciones
- No utilizar ninguna API externa, de visión o LLM (ni Gemini ni OpenAI). El contexto de esta skill es estrictamente para recabar la cadena de texto base que proporciona PyMuPDF de manera ultra-rápida.
- Los JSONL deben ser nombrados usando el UUID del `id_documento`, no el nombre del archivo original, y deben depositarse exclusivamente en `extracted_text/`.
