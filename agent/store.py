"""Acceso a datos del agente: pendientes del pipeline, hallazgos web y promoción al maestro.

Todo lo que el agente aprende de internet se guarda en tablas propias (agent_*) dentro de
master_entities.sqlite, con URL y cita textual de cada dato. Solo un RUC con confianza ALTA
se promueve a master_entities, y siempre con la misma forma de evidencia que usa el Paso 8.
"""
import glob
import json
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from ruc import validar_ruc

BASE = Path(__file__).resolve().parent.parent
OUTPUT = BASE / "data" / "output"
INPUT = BASE / "data" / "input"
MASTER = Path(os.environ.get("LECTOR_MASTER_DB") or BASE / "data" / "master" / "master_entities.sqlite")

CAMPOS_DEFAULT = ["ruc", "razon_social_oficial", "estado_legal", "tipo_compania", "provincia",
                  "canton", "direccion", "actividad_economica", "fecha_constitucion",
                  "representante_legal"]
TIPOS_EXCLUIDOS = {"PERSONA_NATURAL", "PERSONA NATURAL", "PERSONA", "AUTORIDAD"}
CONFIANZAS = ("ALTA", "MEDIA", "BAJA")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clave TEXT NOT NULL, ruc TEXT, campo TEXT NOT NULL, valor TEXT NOT NULL,
    fuente_url TEXT, evidencia TEXT, confianza TEXT NOT NULL,
    checksum_ok INTEGER, fecha TEXT NOT NULL,
    UNIQUE (clave, campo, valor, fuente_url)
);
CREATE TABLE IF NOT EXISTS agent_research_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clave TEXT NOT NULL, estrategia TEXT, consulta TEXT, resultado TEXT, fecha TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_entity_status (
    clave TEXT PRIMARY KEY, razon_social TEXT, estado TEXT NOT NULL,
    ruc TEXT, notas TEXT, intentos INTEGER DEFAULT 0, fecha_actualizacion TEXT
);
CREATE INDEX IF NOT EXISTS idx_findings_clave ON agent_findings (clave);
"""


def ahora():
    return datetime.now().isoformat(timespec="seconds")


def norm(texto) -> str:
    return re.sub(r"\s+", " ", str(texto or "")).strip().upper()


def conectar() -> sqlite3.Connection:
    MASTER.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(MASTER)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    # master_entities puede no existir si todavía no se corrió el Paso 8
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS master_entities (ruc TEXT PRIMARY KEY, razon_social_canonica TEXT NOT NULL,
            razon_social_normalizada TEXT NOT NULL, tipo_entidad TEXT, provincia_preferida TEXT,
            estado_resolucion_master TEXT, fuente_primaria TEXT, fecha_primera_aparicion TEXT,
            fecha_ultima_actualizacion TEXT, total_lotes_detectado INTEGER DEFAULT 1, total_menciones INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS master_evidence (id INTEGER PRIMARY KEY AUTOINCREMENT, ruc TEXT NOT NULL,
            lote TEXT NOT NULL, archivo_origen TEXT, pagina_pdf INTEGER, fragmento_evidencia TEXT,
            estado_resolucion_origen TEXT, fecha_ingesta TEXT, fuente_ruc TEXT);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_evidence_unique
            ON master_evidence (ruc, lote, archivo_origen, fragmento_evidencia);
    """)
    return conn


def leer_jsonl(path):
    out = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.strip():
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return out


def lote_de(nombre_zip: str) -> str:
    return nombre_zip[:-4] if nombre_zip.lower().endswith(".zip") else nombre_zip


def zips_sin_procesar():
    with conectar() as conn:
        hechos = {r[0] for r in conn.execute("SELECT lote_base FROM processed_batches")} \
            if conn.execute("SELECT name FROM sqlite_master WHERE name='processed_batches'").fetchone() else set()
    return [p.name for p in sorted(INPUT.glob("*.zip")) if lote_de(p.name) not in hechos]


def _registros_pendientes(lote=None):
    archivos = glob.glob(str(OUTPUT / "not_ready_for_master_*.jsonl")) + \
        glob.glob(str(OUTPUT / "manual_review_*.jsonl"))
    for a in sorted(archivos):
        for r in leer_jsonl(a):
            if lote and lote_de(r.get("lote", "")) != lote_de(lote):
                continue
            yield r


def pendientes_ruc(lote=None, limite=20, incluir_cerrados=False):
    """Entidades sin RUC, agrupadas por nombre normalizado a través de todos los lotes."""
    with conectar() as conn:
        en_maestro = {r[0] for r in conn.execute("SELECT razon_social_normalizada FROM master_entities")}
        estados = {r["clave"]: r for r in conn.execute("SELECT * FROM agent_entity_status")}
    grupos, omitidos = {}, {}
    for r in _registros_pendientes(lote):
        orig = r.get("candidato_original") or {}
        nombre = r.get("razon_social_candidata") or orig.get("razon_social_original") or ""
        clave = norm(r.get("razon_social_normalizada") or nombre)
        tipo = norm(orig.get("tipo_entidad_detectada"))
        if r.get("ruc_final") or clave in en_maestro:
            continue
        if tipo in TIPOS_EXCLUIDOS or r.get("estado_resolucion") == "TEXTO_ILEGIBLE" or len(clave) < 5:
            omitidos[clave] = tipo or "NOMBRE_CORTO_O_ILEGIBLE"
            continue
        st = estados.get(clave)
        if st and not incluir_cerrados and st["estado"] in ("ENCONTRADO", "NO_ENCONTRADO", "REVISION_MANUAL"):
            continue
        g = grupos.setdefault(clave, {
            "clave": clave, "razon_social": nombre, "tipo_entidad": tipo,
            "provincias": set(), "estado_previo": st["estado"] if st else "PENDIENTE",
            "intentos_previos": st["intentos"] if st else 0, "apariciones": []})
        prov = orig.get("provincia_mencionada")
        if prov and str(prov).lower() not in ("null", "sin_dato", "none"):
            g["provincias"].add(prov)
        g["apariciones"].append({
            "lote": r.get("lote"), "archivos": orig.get("archivos_origen", []),
            "paginas": orig.get("paginas_origen", []),
            "fragmentos": (orig.get("fragmentos_evidencia") or [])[:3],
            "menciones": orig.get("menciones_totales", 1),
            "observaciones_pipeline": (r.get("observaciones") or "")[:200]})
    lista = []
    for g in grupos.values():
        g["provincias"] = sorted(g["provincias"])
        lista.append(g)
        if len(lista) >= limite:
            break
    return lista, {"total_pendientes": len(grupos), "omitidos": len(omitidos),
                   "omitidos_por": sorted(set(omitidos.values()))}


def pendientes_campos(campos, limite=20):
    """Entidades ya en el maestro a las que les faltan campos por investigar."""
    campos = [c for c in campos if c != "ruc"]
    with conectar() as conn:
        lista = []
        for e in conn.execute("SELECT * FROM master_entities ORDER BY total_menciones DESC"):
            clave = e["razon_social_normalizada"]
            tengo = {r[0] for r in conn.execute("SELECT DISTINCT campo FROM agent_findings WHERE clave=?", (clave,))}
            faltan = [c for c in campos if c not in tengo]
            if faltan:
                lista.append({"clave": clave, "razon_social": e["razon_social_canonica"], "ruc": e["ruc"],
                              "provincia_conocida": e["provincia_preferida"], "campos_faltantes": faltan})
            if len(lista) >= limite:
                break
    return lista


def contexto_pdf(lote, archivo, pagina, max_chars=6000):
    ruta = OUTPUT / f"consolidated_{lote_de(lote)}.jsonl"
    if not ruta.exists():
        return None
    for r in leer_jsonl(ruta):
        if r.get("archivo_origen") == archivo and str(r.get("pagina_pdf")) == str(pagina):
            return (r.get("texto_crudo") or "")[:max_chars]
    return None


def buscar_catalogo(consulta, limite=10):
    """Busca en los catastros locales (SRI, SEPS) por nombre (FTS) o por RUC exacto."""
    db = BASE / "data" / "external" / "catalogs.sqlite"
    if not db.exists():
        return []
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    try:
        if re.fullmatch(r"\d{10,13}", consulta.strip()):
            rows = c.execute("SELECT ruc, razon_social, provincia, tipo, fuente FROM entities WHERE ruc LIKE ? LIMIT ?",
                             (consulta.strip() + "%", limite)).fetchall()
        else:
            palabras = [p for p in re.sub(r"[^A-Z0-9\s]", " ", consulta.upper()).split() if len(p) > 2]
            if not palabras:
                return []
            fts = " AND ".join(f'"{p}*"' for p in palabras)
            rows = c.execute("""SELECT e.ruc, e.razon_social, e.provincia, e.tipo, e.fuente
                                FROM entities_fts f JOIN entities e ON f.ruc = e.ruc
                                WHERE entities_fts MATCH ? ORDER BY rank LIMIT ?""", (fts, limite)).fetchall()
        return [dict(r) for r in rows]
    finally:
        c.close()


def registrar_intento(clave, estrategia, consulta, resultado):
    with conectar() as conn:
        conn.execute("INSERT INTO agent_research_log (clave, estrategia, consulta, resultado, fecha) VALUES (?,?,?,?,?)",
                     (norm(clave), estrategia, consulta, (resultado or "")[:500], ahora()))
        conn.execute("""INSERT INTO agent_entity_status (clave, estado, intentos, fecha_actualizacion)
                        VALUES (?, 'EN_INVESTIGACION', 1, ?)
                        ON CONFLICT(clave) DO UPDATE SET intentos = intentos + 1, fecha_actualizacion = excluded.fecha_actualizacion,
                        estado = CASE WHEN estado IN ('ENCONTRADO') THEN estado ELSE 'EN_INVESTIGACION' END""",
                     (norm(clave), ahora()))
        n = conn.execute("SELECT intentos FROM agent_entity_status WHERE clave=?", (norm(clave),)).fetchone()[0]
    return n


def registrar_hallazgo(clave, campo, valor, fuente_url, evidencia, confianza, ruc=None):
    """Guarda un dato con su prueba. Rechaza lo que no venga respaldado."""
    clave, campo, valor = norm(clave), campo.strip().lower(), str(valor).strip()
    confianza = norm(confianza)
    if confianza not in CONFIANZAS:
        return {"ok": False, "error": f"confianza debe ser una de {CONFIANZAS}"}
    if not valor:
        return {"ok": False, "error": "valor vacío"}
    if valor != "NO_DISPONIBLE":
        if not str(fuente_url or "").startswith("http"):
            return {"ok": False, "error": "fuente_url debe ser la URL http(s) real donde viste el dato"}
        if len((evidencia or "").strip()) < 10:
            return {"ok": False, "error": "evidencia debe ser la cita textual (copiada de la página) que respalda el dato"}
    checksum = None
    if campo == "ruc":
        valor = re.sub(r"\D", "", valor)
        if len(valor) != 13:
            return {"ok": False, "error": "un RUC tiene 13 dígitos"}
        if valor not in re.sub(r"\D", "", evidencia or "") and valor not in (evidencia or ""):
            return {"ok": False, "error": "la evidencia citada no contiene ese RUC; copia el texto exacto de la página donde aparece junto al nombre de la empresa"}
        checksum = int(validar_ruc(valor)["valido"])
        ruc = valor
    with conectar() as conn:
        try:
            conn.execute("""INSERT INTO agent_findings (clave, ruc, campo, valor, fuente_url, evidencia, confianza, checksum_ok, fecha)
                            VALUES (?,?,?,?,?,?,?,?,?)""",
                         (clave, ruc, campo, valor, fuente_url, evidencia, confianza, checksum, ahora()))
        except sqlite3.IntegrityError:
            return {"ok": True, "nota": "ya estaba registrado"}
    return {"ok": True, "checksum_ruc_valido": None if checksum is None else bool(checksum)}


def _evidencias_de(clave):
    por_lote = {}
    for r in _registros_pendientes():
        orig = r.get("candidato_original") or {}
        if norm(r.get("razon_social_normalizada") or orig.get("razon_social_original")) != clave:
            continue
        por_lote.setdefault(r.get("lote"), []).append(orig)
    return por_lote


def _promover(conn, clave, ruc, url):
    f = {r["campo"]: r["valor"] for r in conn.execute(
        "SELECT campo, valor FROM agent_findings WHERE clave=? AND confianza IN ('ALTA','MEDIA') ORDER BY id", (clave,))}
    por_lote = _evidencias_de(clave)
    ts = ahora()
    existe = conn.execute("SELECT 1 FROM master_entities WHERE ruc=?", (ruc,)).fetchone()
    nuevos_lotes = menciones_nuevas = 0
    for lote, origs in por_lote.items():
        ya = conn.execute("SELECT 1 FROM master_evidence WHERE ruc=? AND lote LIKE ?", (ruc, lote_de(lote) + "%")).fetchone()
        insertadas = 0
        for orig in origs:
            archivos, paginas, frags = orig.get("archivos_origen", []), orig.get("paginas_origen", []), orig.get("fragmentos_evidencia", [])
            for i in range(max(len(archivos), len(paginas), len(frags), 1)):
                a = archivos[i] if i < len(archivos) else (archivos[-1] if archivos else "Desconocido")
                p = paginas[i] if i < len(paginas) else (paginas[-1] if paginas else 0)
                fr = frags[i] if i < len(frags) else (frags[-1] if frags else "")
                cur = conn.execute("""INSERT OR IGNORE INTO master_evidence (ruc, lote, archivo_origen, pagina_pdf,
                    fragmento_evidencia, estado_resolucion_origen, fecha_ingesta, fuente_ruc) VALUES (?,?,?,?,?,?,?,?)""",
                    (ruc, lote, a, int(p) if str(p).isdigit() else 0, str(fr), "RUC_WEB_AGENTE", ts, "WEB_AGENTE:" + url))
                insertadas += cur.rowcount
        if insertadas and not ya:
            nuevos_lotes += 1
            menciones_nuevas += sum(o.get("menciones_totales", 1) for o in origs)
    if existe:
        conn.execute("""UPDATE master_entities SET total_lotes_detectado = total_lotes_detectado + ?,
                        total_menciones = total_menciones + ?, fecha_ultima_actualizacion = ? WHERE ruc = ?""",
                     (nuevos_lotes, menciones_nuevas, ts, ruc))
    else:
        any_orig = next((o for os_ in por_lote.values() for o in os_), {})
        conn.execute("""INSERT INTO master_entities (ruc, razon_social_canonica, razon_social_normalizada, tipo_entidad,
            provincia_preferida, estado_resolucion_master, fuente_primaria, fecha_primera_aparicion,
            fecha_ultima_actualizacion, total_lotes_detectado, total_menciones) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (ruc, f.get("razon_social_oficial") or any_orig.get("razon_social_original") or clave, clave,
             any_orig.get("tipo_entidad_detectada", "DESCONOCIDO"), f.get("provincia") or any_orig.get("provincia_mencionada") or "DESCONOCIDA",
             "RUC_WEB_AGENTE", url, ts, ts, max(nuevos_lotes, 1), max(menciones_nuevas, 1)))
    return {"entidad_nueva": not existe, "lotes_vinculados": nuevos_lotes}


def cerrar_entidad(clave, estado, notas=""):
    """estado: ENCONTRADO | NO_ENCONTRADO | REVISION_MANUAL. ENCONTRADO exige un RUC con confianza ALTA."""
    clave = norm(clave)
    if estado not in ("ENCONTRADO", "NO_ENCONTRADO", "REVISION_MANUAL"):
        return {"ok": False, "error": "estado inválido"}
    with conectar() as conn:
        ruc, promo = None, None
        if estado == "ENCONTRADO":
            rucs = conn.execute("""SELECT valor, fuente_url FROM agent_findings
                                   WHERE clave=? AND campo='ruc' AND confianza='ALTA' ORDER BY id DESC""", (clave,)).fetchall()
            distintos = {r["valor"] for r in rucs}
            if not rucs:
                return {"ok": False, "error": "no hay hallazgo 'ruc' con confianza ALTA; registra uno o cierra como REVISION_MANUAL/NO_ENCONTRADO"}
            if len(distintos) > 1:
                estado, notas = "REVISION_MANUAL", f"RUC contradictorios: {sorted(distintos)}. {notas}"
            else:
                ruc = rucs[0]["valor"]
                promo = _promover(conn, clave, ruc, rucs[0]["fuente_url"])
        conn.execute("""INSERT INTO agent_entity_status (clave, estado, ruc, notas, intentos, fecha_actualizacion)
                        VALUES (?,?,?,?,0,?) ON CONFLICT(clave) DO UPDATE SET estado=excluded.estado, ruc=excluded.ruc,
                        notas=excluded.notas, fecha_actualizacion=excluded.fecha_actualizacion""",
                     (clave, estado, ruc, notas, ahora()))
    return {"ok": True, "estado_final": estado, "ruc": ruc, "maestro": promo}


def exportar_enriquecido(destino=None):
    """Una fila por entidad con el mejor dato de cada campo investigado (xlsx)."""
    import pandas as pd
    destino = Path(destino or OUTPUT / "entidades_enriquecidas.xlsx")
    rango = {"ALTA": 0, "MEDIA": 1, "BAJA": 2}
    with conectar() as conn:
        filas = {}
        for e in conn.execute("SELECT ruc, razon_social_canonica, razon_social_normalizada, estado_resolucion_master FROM master_entities"):
            filas[e["razon_social_normalizada"]] = {"ruc": e["ruc"], "razon_social": e["razon_social_canonica"],
                                                    "origen_ruc": e["estado_resolucion_master"]}
        for r in conn.execute("SELECT clave, razon_social, estado, ruc FROM agent_entity_status"):
            filas.setdefault(r["clave"], {"ruc": r["ruc"], "razon_social": r["razon_social"] or r["clave"]})["estado_agente"] = r["estado"]
        hallazgos = conn.execute("SELECT * FROM agent_findings").fetchall()
    mejor = {}
    for h in sorted(hallazgos, key=lambda h: (rango[h["confianza"]], -h["id"])):
        mejor.setdefault((h["clave"], h["campo"]), h)
    for (clave, campo), h in mejor.items():
        fila = filas.setdefault(clave, {"razon_social": clave})
        fila[campo] = h["valor"]
        fila[f"{campo}__fuente"] = h["fuente_url"]
    df = pd.DataFrame(list(filas.values()))
    destino.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(destino, index=False)
    return str(destino), len(df)
