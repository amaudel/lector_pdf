---
name: batch-unzipper
description: Automatiza la extracción segura de un lote ZIP y genera un inventario de los PDFs contenidos con trazabilidad.
---

# Objetivo
Descomprimir un archivo ZIP proveído en la carpeta temporal de trabajo y generar un índice estandarizado (`inventory.json`) limitando el contexto a archivos PDF válidos e ignorando formatos incompatibles.

# Instrucciones
Cuando debas usar esta skill:
1. Asegúrate de tener la ruta absoluta al archivo ZIP (usualmente en `data/input/lote.zip`) y la ruta a la carpeta temporal `data/temp/`.
2. Ejecuta el comando en terminal:
   `python scripts/1_unzip_and_inventory.py --zip_path "RUTA_AL_ZIP" --temp_dir "RUTA_AL_TEMP"`
3. Verifica la salida en la terminal para confirmar que se generó `inventory.json` correctamente y reporta al usuario los PDFs encontrados y archivos ignorados.

# Restricciones
- NO modifiques el ZIP original bajo ninguna circunstancia.
- NO extraigas datos fuera de la subcarpeta del lote dentro de `data/temp/`.
