export interface Env {
  DB: D1Database;
  ARCHIVOS: R2Bucket;
  PIPELINE: Workflow<PipelineParams>;
  INVESTIGADOR: Workflow<InvestigadorParams>;
  // secrets
  OPENAI_API_KEY: string;
  API_TOKEN: string;
  // vars
  MODELO_EXTRACCION: string;
  MODELO_AGENTE: string;
  CRON_ACTIVO?: string;
  CRON_ZIPS_POR_DIA?: string;
  CRON_ENTIDADES_POR_DIA?: string;
  MAX_ITER_AGENTE?: string;
  /** Solo para pruebas locales contra un OpenAI simulado. */
  OPENAI_BASE_URL?: string;
  /** Solo pruebas locales: permite que leer_pagina abra http://127.0.0.1. Nunca definir en producción. */
  PRUEBAS_URL_LOCAL?: string;
}

export interface PipelineParams {
  zip: string;           // nombre del objeto en R2 bajo input/
  investigar: boolean;   // encadenar el agente investigador al terminar
  limite: number;        // máximo de entidades a investigar
  forzar: boolean;       // re-procesar un lote ya integrado al maestro
}

export interface InvestigadorParams {
  limite: number;
  claves?: string[];     // si se indica, solo estas entidades
}
