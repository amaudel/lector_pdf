-- ============ PIPELINE (reemplaza los .jsonl intermedios) ============
CREATE TABLE IF NOT EXISTS lotes (
  lote TEXT PRIMARY KEY, zip_key TEXT, zip_sha256 TEXT, estado TEXT NOT NULL, workflow_id TEXT,
  fecha_inicio TEXT, fecha_fin TEXT, resumen TEXT
);
CREATE INDEX IF NOT EXISTS idx_lotes_sha ON lotes (zip_sha256);
CREATE TABLE IF NOT EXISTS documentos (
  id TEXT PRIMARY KEY, lote TEXT NOT NULL, archivo_origen TEXT, ruta_en_zip TEXT,
  r2_key TEXT, tamano INTEGER, sha256 TEXT, paginas INTEGER
);
CREATE INDEX IF NOT EXISTS idx_doc_lote ON documentos (lote);
CREATE TABLE IF NOT EXISTS paginas (
  id INTEGER PRIMARY KEY AUTOINCREMENT, lote TEXT NOT NULL, id_documento TEXT NOT NULL,
  archivo_origen TEXT, pagina INTEGER NOT NULL, estado TEXT NOT NULL, texto TEXT,
  UNIQUE (id_documento, pagina)
);
CREATE INDEX IF NOT EXISTS idx_pag_lote ON paginas (lote);
CREATE TABLE IF NOT EXISTS entidades_extraidas (
  id INTEGER PRIMARY KEY AUTOINCREMENT, lote TEXT NOT NULL, id_documento TEXT, archivo_origen TEXT,
  pagina INTEGER, razon_social_original TEXT, ruc_detectado TEXT, provincia TEXT, tipo TEXT,
  fragmento TEXT, confianza TEXT, estado_entidad TEXT
);
CREATE INDEX IF NOT EXISTS idx_ent_lote ON entidades_extraidas (lote);
CREATE TABLE IF NOT EXISTS candidatos (
  id INTEGER PRIMARY KEY AUTOINCREMENT, lote TEXT NOT NULL, clave TEXT NOT NULL,
  razon_social_original TEXT, razon_social_normalizada TEXT, tipo_entidad TEXT, provincia TEXT,
  ruc_detectado TEXT, menciones INTEGER, archivos TEXT, paginas TEXT, fragmentos TEXT,
  provincia_consistente TEXT, tipo_consistente TEXT, confianza TEXT, estado_candidato TEXT,
  ruc_final TEXT, fuente_ruc TEXT, estado_resolucion TEXT, coincidencia_nombre TEXT,
  coincidencia_provincia TEXT, provincia_oficial TEXT, sucursal_azuay TEXT, observaciones TEXT,
  apto_maestro INTEGER DEFAULT 0,
  UNIQUE (lote, clave)
);
CREATE INDEX IF NOT EXISTS idx_cand_pend ON candidatos (apto_maestro, ruc_final);

-- ============ MAESTRO (mismo esquema que master_entities.sqlite local) ============
CREATE TABLE IF NOT EXISTS master_entities (
  ruc TEXT PRIMARY KEY, razon_social_canonica TEXT NOT NULL, razon_social_normalizada TEXT NOT NULL,
  tipo_entidad TEXT, provincia_preferida TEXT, estado_resolucion_master TEXT, fuente_primaria TEXT,
  fecha_primera_aparicion TEXT, fecha_ultima_actualizacion TEXT,
  total_lotes_detectado INTEGER DEFAULT 1, total_menciones INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_master_norm ON master_entities (razon_social_normalizada);
CREATE TABLE IF NOT EXISTS master_evidence (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ruc TEXT NOT NULL, lote TEXT NOT NULL, archivo_origen TEXT,
  pagina_pdf INTEGER, fragmento_evidencia TEXT, estado_resolucion_origen TEXT, fecha_ingesta TEXT, fuente_ruc TEXT
);
CREATE INDEX IF NOT EXISTS idx_evidence_ruc ON master_evidence (ruc);
CREATE INDEX IF NOT EXISTS idx_evidence_lote ON master_evidence (lote);
CREATE UNIQUE INDEX IF NOT EXISTS idx_evidence_unique ON master_evidence (ruc, lote, archivo_origen, fragmento_evidencia);
CREATE TABLE IF NOT EXISTS processed_batches (
  lote_base TEXT PRIMARY KEY, fecha_procesamiento TEXT, total_registros_leidos INTEGER,
  total_insertados INTEGER, total_actualizados INTEGER, referencia_archivo TEXT
);

-- ============ AGENTE INVESTIGADOR ============
CREATE TABLE IF NOT EXISTS agent_findings (
  id INTEGER PRIMARY KEY AUTOINCREMENT, clave TEXT NOT NULL, ruc TEXT, campo TEXT NOT NULL, valor TEXT NOT NULL,
  fuente_url TEXT, evidencia TEXT, confianza TEXT NOT NULL, verificado_en_pagina INTEGER,
  checksum_ok INTEGER, fecha TEXT NOT NULL,
  UNIQUE (clave, campo, valor, fuente_url)
);
CREATE INDEX IF NOT EXISTS idx_findings_clave ON agent_findings (clave);
CREATE TABLE IF NOT EXISTS agent_research_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, clave TEXT NOT NULL, estrategia TEXT, consulta TEXT, resultado TEXT, fecha TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_entity_status (
  clave TEXT PRIMARY KEY, razon_social TEXT, estado TEXT NOT NULL, ruc TEXT, notas TEXT,
  intentos INTEGER DEFAULT 0, fecha_actualizacion TEXT
);

-- ============ CATÁLOGO LOCAL (SEPS / SRI), opcional ============
CREATE TABLE IF NOT EXISTS catalogo (
  ruc TEXT, razon_social TEXT, provincia TEXT, tipo TEXT, fuente TEXT
);
CREATE INDEX IF NOT EXISTS idx_catalogo_ruc ON catalogo (ruc);
CREATE VIRTUAL TABLE IF NOT EXISTS catalogo_fts USING fts5(razon_social, content='catalogo', content_rowid='rowid');
