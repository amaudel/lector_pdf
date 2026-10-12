---
name: entity-deduplicator
description: Depura el archivo entities_extracted generado por el LLM, eliminando ruidos, agrupando menciones idénticas (deduplicación cruzando RUCs lógicos) y levantando a un nivel de Candidato Único.
---

# Objetivo
Ejecutar la Subfase Analítica (Fase 2.5). Entiende que las entidades recolectadas página por página poseen alta redundancia. Aplica heurísticas deterministas (Normalización de Razón Social y Match de RUCs) para colapsar N menciones en 1 Candidato Empresa con matrices de confianza (`estado_candidato`).

# Instrucciones
Cuando debas usar esta skill:
1. Asegúrate de que existe el compilado semántico (`data/output/entities_extracted_[lote_base].jsonl`).
2. Ejecuta el comando en terminal:
   `python scripts/5_deduplicate_entities.py --entities_path "RUTA_AL_ENTITIES_JSONL" --output_dir "data/output"`
3. Inspecciona el `candidates_report` y notifica cuántos candidatos existen en `LISTA_PARA_BUSQUEDA`.

# Restricciones
- Solo opera mediante Python nativo (String matching, Regex). No debe consultar ninguna API de OpenAI, por temas de costos no queremos quemar tokens iterando sobre diccionarios redundantes.
- Respeta los fragmentos de evidencia, pero no puede juntar más de 3 por cada candidato para no entorpecer la carga de sistemas.
