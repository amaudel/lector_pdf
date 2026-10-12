---
name: entity-extractor
description: Lee el archivo maestro consolidated.jsonl consumiendo el "texto_crudo" y delegando a un LLM (Gemini) la tarea estricta de recolectar entidades empresariales explícitas sin alucinaciones.
---

# Objetivo
Ejecutar la Fase 2 del proceso. Identifica sistemáticamente y captura razones sociales, RUCs explícitos y provincias utilizando `texto_crudo` procesado en el Paso 3, delegando a un LLM de OpenAI. El formato de salida es un nuevo `.jsonl` que proyecta la base documental hacia dimensiones de entidades semánticas con sus respectivos niveles de confianza.

# Instrucciones
Cuando debas usar esta skill:
1. Asegúrate de que existe un compilado maestro de texto limpio (`data/output/consolidated_[lote_base].jsonl`).
2. Confirma al usuario que vas a incurrir en consultas a un modelo de OpenAI (Requiere `OPENAI_API_KEY` en el entorno).
3. Ejecuta el comando en terminal:
   `python scripts/4_extract_entities.py --consolidated_path "RUTA_AL_CONSOLIDADO_JSONL" --output_dir "data/output"`
4. La extracción depositará un `entities_extracted_[lote_base].jsonl` mapeando N entidades detectadas por cada página.

# Restricciones
- La instrucción central en el Prompt del LLM prohíbe **estrictamente** intuir RUCs que no están escritos.
- Prohíbe inventar provincias que no figuran nativamente.
- No utiliza cruces con SRI ni Supercias (todavía).
- Maneja rate-limiting de facto por el `time.sleep` dentro del código para no quebrar cuotas de la API.
