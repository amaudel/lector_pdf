import type { Env } from "../env";
import { ahora, normalizarComparacion, sinTildes, tokensNucleo } from "../norm";
import { sentenciasEvidencia } from "../pipeline/master";
import { validarRuc } from "../ruc";
import { leerPagina } from "./paginas";

export const CAMPOS_DEFAULT = ["ruc", "razon_social_oficial", "estado_legal", "tipo_compania", "provincia", "canton",
  "direccion", "actividad_economica", "fecha_constitucion", "representante_legal"];
const TIPOS_EXCLUIDOS = new Set(["PERSONA_NATURAL", "PERSONA NATURAL", "PERSONA", "AUTORIDAD"]);
const CONFIANZAS = ["ALTA", "MEDIA", "BAJA"] as const;
type Confianza = (typeof CONFIANZAS)[number];
const DOMINIOS_OFICIALES = ["sri.gob.ec", "supercias.gob.ec", "scvs.gob.ec", "seps.gob.ec", "registromercantil.gob.ec",
  "compraspublicas.gob.ec", "sercop.gob.ec", "registroficial.gob.ec", "funcionjudicial.gob.ec"];

const norm = (s: unknown): string => String(s ?? "").replace(/\s+/g, " ").trim().toUpperCase();

export interface Pendiente {
  clave: string; razon_social: string; tipo_entidad: string; provincias: string[]; estado_previo: string; intentos_previos: number;
  apariciones: { lote: string; archivos: string[]; paginas: number[]; fragmentos: string[]; menciones: number; observaciones: string }[];
}

const json = <T>(s: string | null, def: T): T => { try { return s ? (JSON.parse(s) as T) : def; } catch { return def; } };

/** Entidades sin RUC, agrupadas por nombre normalizado a través de todos los lotes. */
export async function pendientes(env: Env, opt: { lote?: string; limite?: number; claves?: string[]; incluirCerrados?: boolean } = {}):
  Promise<{ lista: Pendiente[]; resumen: { total_pendientes: number; omitidos: number } }> {
  const [filas, enMaestro, estados] = await Promise.all([
    env.DB.prepare("SELECT * FROM candidatos WHERE apto_maestro = 0 AND ruc_final IS NULL AND estado_candidato = 'LISTA_PARA_BUSQUEDA' ORDER BY id").all<any>(),
    env.DB.prepare("SELECT razon_social_normalizada AS n FROM master_entities").all<{ n: string }>(),
    env.DB.prepare("SELECT * FROM agent_entity_status").all<any>(),
  ]);
  const maestro = new Set(enMaestro.results.map((r) => r.n));
  const est = new Map(estados.results.map((r: any) => [r.clave, r]));
  const grupos = new Map<string, Pendiente>();
  let omitidos = 0;
  for (const r of filas.results) {
    if (opt.lote && r.lote !== opt.lote) continue;
    const clave = norm(r.razon_social_normalizada);
    if (opt.claves && !opt.claves.includes(clave)) continue;
    if (maestro.has(clave)) continue;
    const tipo = norm(r.tipo_entidad);
    if (TIPOS_EXCLUIDOS.has(tipo) || r.estado_resolucion === "TEXTO_ILEGIBLE" || clave.length < 5) { omitidos++; continue; }
    const st = est.get(clave) as any;
    if (st && !opt.incluirCerrados && ["ENCONTRADO", "NO_ENCONTRADO", "REVISION_MANUAL"].includes(st.estado)) continue;
    let g = grupos.get(clave);
    if (!g) { g = { clave, razon_social: r.razon_social_original || clave, tipo_entidad: tipo, provincias: [], estado_previo: st?.estado ?? "PENDIENTE", intentos_previos: st?.intentos ?? 0, apariciones: [] }; grupos.set(clave, g); }
    if (r.provincia && !["NULL", "NONE", "SIN_DATO"].includes(String(r.provincia).toUpperCase()) && !g.provincias.includes(r.provincia)) g.provincias.push(r.provincia);
    g.apariciones.push({ lote: r.lote, archivos: json(r.archivos, []), paginas: json(r.paginas, []), fragmentos: json<string[]>(r.fragmentos, []).slice(0, 3), menciones: r.menciones, observaciones: String(r.observaciones || "").slice(0, 200) });
  }
  const todos = [...grupos.values()];
  return { lista: todos.slice(0, opt.limite ?? 10), resumen: { total_pendientes: todos.length, omitidos } };
}

export async function contextoPdf(env: Env, lote: string, archivo: string, pagina: number): Promise<string | null> {
  const r = await env.DB.prepare("SELECT texto FROM paginas WHERE lote = ? AND archivo_origen = ? AND pagina = ?").bind(lote, archivo, pagina).first<{ texto: string }>();
  return r?.texto ? r.texto.slice(0, 6000) : null;
}

export async function buscarCatalogo(env: Env, consulta: string, limite = 10): Promise<unknown[]> {
  const q = consulta.trim();
  try {
    if (/^\d{10,13}$/.test(q)) return (await env.DB.prepare("SELECT ruc, razon_social, provincia, tipo, fuente FROM catalogo WHERE ruc LIKE ? LIMIT ?").bind(q + "%", limite).all()).results;
    const palabras = q.toUpperCase().replace(/[^A-Z0-9\s]/g, " ").split(/\s+/).filter((p) => p.length > 2);
    if (!palabras.length) return [];
    return (await env.DB.prepare(`SELECT c.ruc, c.razon_social, c.provincia, c.tipo, c.fuente FROM catalogo_fts f JOIN catalogo c ON c.rowid = f.rowid
      WHERE catalogo_fts MATCH ? LIMIT ?`).bind(palabras.map((p) => `"${p}"`).join(" "), limite).all()).results;
  } catch { return []; }
}

export async function registrarIntento(env: Env, clave: string, estrategia: string, consulta: string, resultado: string): Promise<number> {
  const c = norm(clave), ts = ahora();
  await env.DB.batch([
    env.DB.prepare("INSERT INTO agent_research_log (clave, estrategia, consulta, resultado, fecha) VALUES (?,?,?,?,?)").bind(c, estrategia, consulta, (resultado || "").slice(0, 500), ts),
    env.DB.prepare(`INSERT INTO agent_entity_status (clave, estado, intentos, fecha_actualizacion) VALUES (?, 'EN_INVESTIGACION', 1, ?)
      ON CONFLICT(clave) DO UPDATE SET intentos = intentos + 1, fecha_actualizacion = excluded.fecha_actualizacion,
      estado = CASE WHEN estado = 'ENCONTRADO' THEN estado ELSE 'EN_INVESTIGACION' END`).bind(c, ts),
  ]);
  return (await env.DB.prepare("SELECT intentos FROM agent_entity_status WHERE clave = ?").bind(c).first<{ intentos: number }>())?.intentos ?? 1;
}

/** ¿El dato aparece realmente en la página citada? Verificación hecha por el servidor, no por el modelo. */
export function valorEnTexto(campo: string, valor: string, texto: string): boolean {
  const t = sinTildes(texto.toUpperCase());
  if (campo === "ruc") return t.replace(/\s/g, "").includes(valor.replace(/\D/g, ""));
  const compacto = normalizarComparacion(texto), v = normalizarComparacion(valor);
  if (v && compacto.includes(v)) return true;
  const toks = tokensNucleo(sinTildes(valor.toUpperCase()));
  return toks.length > 0 && toks.filter((x) => t.includes(x)).length / toks.length >= 0.8;
}
const nombreEnTexto = (nombre: string, texto: string): boolean => valorEnTexto("razon_social", nombre, texto);

const dominio = (u: string): string => { try { return new URL(u).hostname.toLowerCase().replace(/^www\./, ""); } catch { return ""; } };
const esOficial = (d: string): boolean => DOMINIOS_OFICIALES.some((o) => d === o || d.endsWith("." + o));

export async function registrarHallazgo(env: Env, clave: string, razonSocial: string, a: {
  campo: string; valor: string; fuente_url?: string; evidencia?: string; confianza: string;
}): Promise<Record<string, unknown>> {
  const c = norm(clave), campo = String(a.campo || "").trim().toLowerCase();
  let valor = String(a.valor ?? "").trim();
  const conf = norm(a.confianza) as Confianza;
  if (!CONFIANZAS.includes(conf)) return { ok: false, error: `confianza debe ser una de ${CONFIANZAS.join(", ")}` };
  if (!campo || !valor) return { ok: false, error: "campo y valor son obligatorios" };
  const url = a.fuente_url || "", evidencia = a.evidencia || "";
  const noDisponible = valor === "NO_DISPONIBLE";
  if (!noDisponible) {
    if (!/^https?:\/\//.test(url)) return { ok: false, error: "fuente_url debe ser la URL http(s) real donde viste el dato" };
    if (evidencia.trim().length < 10) return { ok: false, error: "evidencia debe ser la cita textual copiada de la página que respalda el dato" };
  }
  let checksum: number | null = null, ruc: string | null = null;
  if (campo === "ruc" && !noDisponible) {
    valor = valor.replace(/\D/g, "");
    if (valor.length !== 13) return { ok: false, error: "un RUC tiene 13 dígitos" };
    if (!evidencia.replace(/\D/g, "").includes(valor) && !evidencia.includes(valor)) return { ok: false, error: "la evidencia citada no contiene ese RUC; copia el texto exacto de la página donde aparece junto al nombre de la empresa" };
    checksum = validarRuc(valor).valido ? 1 : 0;
    ruc = valor;
  }
  // Verificación del lado del servidor: leemos la página citada y comprobamos que el dato (y, para el RUC, el nombre) estén ahí.
  let verificado: number | null = null, nota = "";
  if (!noDisponible) {
    const pag = await leerPagina(url, env.PRUEBAS_URL_LOCAL === "true");
    if (!pag.ok) { verificado = null; nota = `No se pudo leer la página para verificar (${pag.error}).`; }
    else {
      const datoOk = valorEnTexto(campo, valor, pag.texto);
      const nombreOk = campo === "ruc" ? nombreEnTexto(razonSocial, pag.texto) : true;
      verificado = datoOk && nombreOk ? 1 : 0;
      if (!verificado) nota = datoOk ? "El nombre de la entidad no aparece en esa página." : "El dato no aparece en esa página.";
    }
  }
  // La confianza que declara el modelo solo puede bajar, nunca subir.
  let tope: Confianza = "BAJA";
  if (noDisponible) tope = conf;
  else if (verificado === 1) {
    const d = dominio(url);
    if (esOficial(d)) tope = "ALTA";
    else {
      const otros = await env.DB.prepare("SELECT fuente_url FROM agent_findings WHERE clave = ? AND campo = ? AND valor = ? AND verificado_en_pagina = 1").bind(c, campo, valor).all<{ fuente_url: string }>();
      tope = otros.results.some((o) => dominio(o.fuente_url) !== d) ? "ALTA" : "MEDIA";
    }
  } else if (verificado === null) tope = "MEDIA";
  const final = CONFIANZAS[Math.max(CONFIANZAS.indexOf(conf), CONFIANZAS.indexOf(tope))];
  try {
    await env.DB.prepare(`INSERT INTO agent_findings (clave, ruc, campo, valor, fuente_url, evidencia, confianza, verificado_en_pagina, checksum_ok, fecha)
      VALUES (?,?,?,?,?,?,?,?,?,?)`).bind(c, ruc, campo, valor, url, evidencia, final, verificado, checksum, ahora()).run();
  } catch (e) {
    if (String(e).includes("UNIQUE")) return { ok: true, nota: "ya estaba registrado" };
    throw e;
  }
  // Si un segundo dominio verificó el mismo RUC, el hallazgo previo también pasa a ALTA.
  if (campo === "ruc" && verificado === 1 && final !== "ALTA") {
    /* el cálculo de 'tope' ya contempla hallazgos previos; el previo se re-evalúa abajo */
  }
  if (campo === "ruc" && verificado === 1) {
    const v = await env.DB.prepare("SELECT id, fuente_url, confianza FROM agent_findings WHERE clave = ? AND campo = 'ruc' AND valor = ? AND verificado_en_pagina = 1").bind(c, valor).all<any>();
    if (new Set(v.results.map((x) => dominio(x.fuente_url))).size >= 2) {
      await env.DB.prepare("UPDATE agent_findings SET confianza = 'ALTA' WHERE clave = ? AND campo = 'ruc' AND valor = ? AND verificado_en_pagina = 1").bind(c, valor).run();
    }
  }
  return { ok: true, confianza_guardada: final, verificado_en_pagina: verificado === null ? "NO_SE_PUDO_LEER" : !!verificado, checksum_ruc_valido: checksum === null ? undefined : !!checksum, nota: nota || undefined };
}

async function promover(env: Env, clave: string, ruc: string, url: string): Promise<Record<string, unknown>> {
  const ts = ahora();
  const f = new Map((await env.DB.prepare("SELECT campo, valor FROM agent_findings WHERE clave = ? AND confianza IN ('ALTA','MEDIA') ORDER BY id").bind(clave).all<{ campo: string; valor: string }>()).results.map((r) => [r.campo, r.valor]));
  const filas = (await env.DB.prepare("SELECT * FROM candidatos WHERE razon_social_normalizada = ? AND apto_maestro = 0 AND ruc_final IS NULL").bind(clave).all<any>()).results;
  const existe = await env.DB.prepare("SELECT 1 AS x FROM master_entities WHERE ruc = ?").bind(ruc).first();
  const stmts: D1PreparedStatement[] = [];
  let lotesNuevos = 0, mencionesNuevas = 0;
  for (const r of filas) {
    const ya = await env.DB.prepare("SELECT 1 AS x FROM master_evidence WHERE ruc = ? AND lote LIKE ?").bind(ruc, r.lote.replace(/\.zip$/i, "") + "%").first();
    stmts.push(...sentenciasEvidencia(env, ruc, r.lote, { archivos: json(r.archivos, []), paginas: json(r.paginas, []), fragmentos: json(r.fragmentos, []) }, "RUC_WEB_AGENTE", "WEB_AGENTE:" + url, ts));
    if (!ya) { lotesNuevos++; mencionesNuevas += r.menciones || 1; }
    stmts.push(env.DB.prepare("UPDATE candidatos SET ruc_final = ?, fuente_ruc = ?, estado_resolucion = 'RUC_WEB_AGENTE', apto_maestro = 1 WHERE id = ?").bind(ruc, "WEB_AGENTE:" + url, r.id));
  }
  const primero = filas[0] ?? {};
  if (existe) stmts.unshift(env.DB.prepare("UPDATE master_entities SET total_lotes_detectado = total_lotes_detectado + ?, total_menciones = total_menciones + ?, fecha_ultima_actualizacion = ? WHERE ruc = ?").bind(lotesNuevos, mencionesNuevas, ts, ruc));
  else stmts.unshift(env.DB.prepare(`INSERT INTO master_entities (ruc, razon_social_canonica, razon_social_normalizada, tipo_entidad, provincia_preferida, estado_resolucion_master,
      fuente_primaria, fecha_primera_aparicion, fecha_ultima_actualizacion, total_lotes_detectado, total_menciones) VALUES (?,?,?,?,?,?,?,?,?,?,?)`)
    .bind(ruc, f.get("razon_social_oficial") || primero.razon_social_original || clave, clave, primero.tipo_entidad || "DESCONOCIDO",
      f.get("provincia") || primero.provincia || "DESCONOCIDA", "RUC_WEB_AGENTE", url, ts, ts, Math.max(lotesNuevos, 1), Math.max(mencionesNuevas, 1)));
  for (let i = 0; i < stmts.length; i += 90) await env.DB.batch(stmts.slice(i, i + 90));
  return { entidad_nueva: !existe, lotes_vinculados: lotesNuevos };
}

/** estado: ENCONTRADO (exige un hallazgo 'ruc' con confianza ALTA) | NO_ENCONTRADO | REVISION_MANUAL. */
export async function cerrarEntidad(env: Env, clave: string, razonSocial: string, estado: string, notas = ""): Promise<Record<string, unknown>> {
  const c = norm(clave);
  if (!["ENCONTRADO", "NO_ENCONTRADO", "REVISION_MANUAL"].includes(estado)) return { ok: false, error: "estado inválido" };
  let ruc: string | null = null, maestro: unknown = null;
  if (estado === "ENCONTRADO") {
    const r = (await env.DB.prepare("SELECT valor, fuente_url FROM agent_findings WHERE clave = ? AND campo = 'ruc' AND confianza = 'ALTA' ORDER BY id DESC").bind(c).all<{ valor: string; fuente_url: string }>()).results;
    if (!r.length) return { ok: false, error: "No hay un hallazgo 'ruc' con confianza ALTA guardada (la confianza la fija el servidor tras verificar la página). Si solo tienes MEDIA/BAJA, cierra como REVISION_MANUAL." };
    const distintos = new Set(r.map((x) => x.valor));
    if (distintos.size > 1) { estado = "REVISION_MANUAL"; notas = `RUC contradictorios: ${[...distintos].join(", ")}. ${notas}`; }
    else { ruc = r[0].valor; maestro = await promover(env, c, ruc, r[0].fuente_url); }
  }
  await env.DB.prepare(`INSERT INTO agent_entity_status (clave, razon_social, estado, ruc, notas, intentos, fecha_actualizacion) VALUES (?,?,?,?,?,0,?)
    ON CONFLICT(clave) DO UPDATE SET razon_social = excluded.razon_social, estado = excluded.estado, ruc = excluded.ruc, notas = excluded.notas, fecha_actualizacion = excluded.fecha_actualizacion`)
    .bind(c, razonSocial, estado, ruc, notas, ahora()).run();
  return { ok: true, estado_final: estado, ruc, maestro };
}
