---
name: external-validator
description: Filtra y procesa los candidatos de Listos para Búsqueda (Fase 3A), preparándolos para comprobación oficial externa y emitiendo un estado determinista final sobre la confianza de la identidad descubierta.
---

# Objetivo
Ejecutar la Fase 3A. Tomar un `.jsonl` de candidatos únicos, discriminar cuáles merecen validación externa de alto costo (evitando basuras o descartes), someterlos metodológicamente a una función proxy, y trazar los hallazgos en un nuevo registro fusionando trazabilidad original con validación externa.

# Instrucciones
Cuando debas usar esta skill:
1. Asegúrate de que existe un `candidates_[lote_base].jsonl` validado por la fase 2.5 previa.
2. Ejecuta en consola:
   `python scripts/6_external_validation.py --candidates_path "data/output/candidates_[lote_base].jsonl" --output_dir "data/output"`
3. El Agente producirá el vector validado oficial (`validated_[lote_base].jsonl`).
4. Revisa las métricas (`-> Probables`) e informa cuántos terminaron con "PROBABLE" en esta iteración sin red y cuántos "NO_PROCESADO".

# Restricciones
- Solo procesa las entidades donde `estado_candidato` es `LISTA_PARA_BUSQUEDA`. Todo lo demás baja como `NO_PROCESADO`.
- El mock actual asume que todo lo que tiene RUC es `PROBABLE`.
- Mantiene íntegros todos los datos de contexto en un sub-diccionario `candidato_original`.
