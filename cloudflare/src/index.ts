import { CAMPOS_DEFAULT, pendientes } from "./agente/store";
import { DASHBOARD_HTML } from "./dashboard";
import type { Env } from "./env";
import { ahora } from "./norm";

export { InvestigadorWorkflow, PipelineWorkflow } from "./workflows";

const json = (d: unknown, status = 200): Response =>
  new Response(JSON.stringify(d), { status, headers: { "content-type": "application/json; charset=utf-8" } });

function nombreZipValido(n: string): boolean {
  return n.length > 4 && n.length < 200 && /\.zip$/i.test(n) && !/[\\/]/.test(n) && !n.includes("..");
}

function autorizado(req: Request, env: Env): boolean {
  if (!env.API_TOKEN) return false; // sin token configurado, la API queda cerrada
  const dado = (req.headers.get("authorization") || "").replace(/^Bearer\s+/i, "");
  if (dado.length !== env.API_TOKEN.length) return false;
  let diff = 0;
  for (let i = 0; i < dado.length; i++) diff |= dado.charCodeAt(i) ^ env.API_TOKEN.charCodeAt(i);
  return diff === 0;
}

async function listarZips(env: Env): Promise<{ nombre: string; bytes: number }[]> {
  const out: { nombre: string; bytes: number }[] = [];
  let cursor: string | undefined;
  do {
    const r = await env.ARCHIVOS.list({ prefix: "input/", cursor });
    for (const o of r.objects) if (/\.zip$/i.test(o.key)) out.push({ nombre: o.key.slice(6), bytes: o.size });
    cursor = r.truncated ? r.cursor : undefined;
  } while (cursor);
  return out;
}

/** ZIP en R2 que todavía no tienen un lote en curso o terminado. Así un lote nuevo se detecta solo, sin importar cuándo se suba. */
async function zipsNuevos(env: Env): Promise<string[]> {
  const [zips, lotes] = await Promise.all([
    listarZips(env),
    env.DB.prepare("SELECT lote, estado FROM lotes").all<{ lote: string; estado: string }>(),
  ]);
  const hechos = new Set(lotes.results.filter((l) => ["COMPLETADO", "EN_PROCESO", "EN_COLA", "DUPLICADO", "SIN_PDFS"].includes(l.estado)).map((l) => l.lote));
  const procesados = new Set((await env.DB.prepare("SELECT lote_base FROM processed_batches").all<{ lote_base: string }>()).results.map((r) => r.lote_base));
  return zips.map((z) => z.nombre).filter((n) => !hechos.has(n) && !procesados.has(n.replace(/\.zip$/i, "")));
}

async function lanzar(env: Env, zip: string, opt: { investigar: boolean; limite: number; forzar?: boolean }): Promise<string> {
  const lote = zip;
  if (!opt.forzar) {
    const ya = await env.DB.prepare("SELECT estado FROM lotes WHERE lote = ?").bind(lote).first<{ estado: string }>();
    if (ya && ["EN_PROCESO", "EN_COLA"].includes(ya.estado)) return "YA_EN_CURSO";
  }
  const id = `${zip.replace(/\.zip$/i, "").replace(/[^A-Za-z0-9_-]/g, "-").slice(0, 60)}-${Date.now().toString(36)}`;
  await env.DB.prepare(`INSERT INTO lotes (lote, zip_key, estado, workflow_id, fecha_inicio) VALUES (?,?,?,?,?)
    ON CONFLICT(lote) DO UPDATE SET estado='EN_COLA', workflow_id=excluded.workflow_id, fecha_inicio=excluded.fecha_inicio`)
    .bind(lote, `input/${zip}`, "EN_COLA", id, ahora()).run();
  await env.PIPELINE.create({ id, params: { zip, investigar: opt.investigar, limite: opt.limite, forzar: !!opt.forzar } });
  return id;
}

async function lanzarNuevos(env: Env, max: number, investigar: boolean, limite: number) {
  const nuevos = await zipsNuevos(env);
  const lanzados: { zip: string; id: string }[] = [];
  for (const zip of nuevos.slice(0, max)) lanzados.push({ zip, id: await lanzar(env, zip, { investigar, limite }) });
  return { lanzados, en_espera: Math.max(nuevos.length - max, 0) };
}

const csv = (filas: Record<string, unknown>[]): string => {
  const cols = [...new Set(filas.flatMap((f) => Object.keys(f)))];
  const celda = (v: unknown) => { const s = String(v ?? ""); return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  return "﻿" + [cols.join(","), ...filas.map((f) => cols.map((c) => celda(f[c])).join(","))].join("\r\n");
};

/** Una fila por entidad con el mejor dato de cada campo investigado. */
export async function filasEnriquecidas(env: Env): Promise<Record<string, unknown>[]> {
  const [m, st, h] = await Promise.all([
    env.DB.prepare("SELECT ruc, razon_social_canonica, razon_social_normalizada, estado_resolucion_master, fuente_primaria, total_lotes_detectado, total_menciones FROM master_entities").all<any>(),
    env.DB.prepare("SELECT clave, razon_social, estado, ruc, notas FROM agent_entity_status").all<any>(),
    env.DB.prepare("SELECT * FROM agent_findings").all<any>(),
  ]);
  const filas = new Map<string, Record<string, any>>();
  for (const e of m.results) filas.set(e.razon_social_normalizada, { ruc: e.ruc, razon_social: e.razon_social_canonica, origen_ruc: e.estado_resolucion_master, fuente_ruc: e.fuente_primaria, lotes: e.total_lotes_detectado, menciones: e.total_menciones });
  for (const s of st.results) { const f = filas.get(s.clave) ?? { ruc: s.ruc, razon_social: s.razon_social || s.clave }; f.estado_agente = s.estado; f.notas_agente = s.notas; filas.set(s.clave, f); }
  const rango: Record<string, number> = { ALTA: 0, MEDIA: 1, BAJA: 2 };
  const mejor = new Map<string, any>();
  for (const x of [...h.results].sort((a, b) => rango[a.confianza] - rango[b.confianza] || b.id - a.id)) {
    const k = `${x.clave}\u0000${x.campo}`;
    if (!mejor.has(k)) mejor.set(k, x);
  }
  for (const x of mejor.values()) {
    const f = filas.get(x.clave) ?? { razon_social: x.clave };
    f[x.campo] = x.valor; f[`${x.campo}__fuente`] = x.fuente_url; f[`${x.campo}__confianza`] = x.confianza; filas.set(x.clave, f);
  }
  return [...filas.values()];
}

async function estado(env: Env) {
  const [zips, nuevos, lotes, maestro, pend, ag] = await Promise.all([
    listarZips(env), zipsNuevos(env),
    env.DB.prepare("SELECT estado, COUNT(*) AS n FROM lotes GROUP BY estado").all<{ estado: string; n: number }>(),
    env.DB.prepare("SELECT COUNT(*) AS n FROM master_entities").first<{ n: number }>(),
    pendientes(env, { limite: 1 }),
    env.DB.prepare("SELECT estado, COUNT(*) AS n FROM agent_entity_status GROUP BY estado").all<{ estado: string; n: number }>(),
  ]);
  return {
    zips_total: zips.length, zips_nuevos: nuevos.length,
    lotes: Object.fromEntries(lotes.results.map((r) => [r.estado, r.n])),
    entidades_maestro: maestro?.n ?? 0, pendientes: pend.resumen.total_pendientes,
    agente: Object.fromEntries(ag.results.map((r) => [r.estado, r.n])),
  };
}

async function api(req: Request, env: Env, url: URL): Promise<Response> {
  const ruta = url.pathname.replace(/^\/api\//, "");
  const m = req.method;

  if (m === "GET" && ruta === "estado") return json(await estado(env));

  if (m === "GET" && ruta === "zips") {
    const [zips, lotes] = await Promise.all([listarZips(env), env.DB.prepare("SELECT lote, estado FROM lotes").all<{ lote: string; estado: string }>()]);
    const est = new Map(lotes.results.map((l) => [l.lote, l.estado]));
    return json(zips.map((z) => ({ ...z, estado: est.get(z.nombre) ?? "NUEVO" })));
  }

  if (m === "PUT" && ruta.startsWith("zips/")) {
    const nombre = decodeURIComponent(ruta.slice(5));
    if (!nombreZipValido(nombre)) return json({ error: "Nombre de ZIP inválido" }, 400);
    if (!req.body) return json({ error: "Cuerpo vacío" }, 400);
    await env.ARCHIVOS.put(`input/${nombre}`, req.body, { httpMetadata: { contentType: "application/zip" } });
    const procesar = url.searchParams.get("procesar") === "1";
    const wf = procesar ? await lanzar(env, nombre, { investigar: url.searchParams.get("investigar") === "1", limite: Math.min(Number(url.searchParams.get("limite") || 5), 50), forzar: url.searchParams.get("forzar") === "1" }) : null;
    return json({ subido: nombre, workflow: wf });
  }

  if (m === "POST" && ruta === "procesar") {
    const b = await req.json<any>().catch(() => ({}));
    if (!nombreZipValido(String(b.zip ?? ""))) return json({ error: "zip inválido" }, 400);
    if (!(await env.ARCHIVOS.head(`input/${b.zip}`))) return json({ error: "ese ZIP no está en R2" }, 404);
    return json({ id: await lanzar(env, b.zip, { investigar: !!b.investigar, limite: Math.min(Number(b.limite ?? 5), 50), forzar: !!b.forzar }) });
  }

  if (m === "POST" && ruta === "procesar-nuevos") {
    const b = await req.json<any>().catch(() => ({}));
    return json(await lanzarNuevos(env, Math.min(Number(b.max ?? 10), 25), !!b.investigar, Math.min(Number(b.limite ?? 5), 50)));
  }

  if (m === "POST" && ruta === "investigar") {
    const b = await req.json<any>().catch(() => ({}));
    const id = `investigar-${Date.now().toString(36)}`;
    await env.INVESTIGADOR.create({ id, params: { limite: Math.min(Number(b.limite ?? 5), 50), claves: Array.isArray(b.claves) ? b.claves : undefined } });
    return json({ id });
  }

  if (m === "GET" && ruta.startsWith("workflow/")) {
    const [, tipo, id] = ruta.split("/");
    const wf = tipo === "investigador" ? env.INVESTIGADOR : env.PIPELINE;
    try { const i = await wf.get(id); return json({ id, estado: await i.status() }); } catch { return json({ error: "no encontrado" }, 404); }
  }

  if (m === "GET" && ruta === "lotes") {
    const r = await env.DB.prepare("SELECT lote, estado, fecha_inicio, fecha_fin, resumen FROM lotes ORDER BY fecha_inicio DESC LIMIT 300").all<any>();
    return json(r.results.map((l) => {
      let corto = "";
      try { const s = JSON.parse(l.resumen || "{}"); corto = s.duplicado_de ? `duplicado de ${s.duplicado_de}` : `${s.pdfs ?? 0} PDF · ${s.candidatos ?? 0} entidades · ${s.aptos_para_maestro ?? 0} con RUC`; } catch { /* sin resumen */ }
      return { ...l, resumen: undefined, resumen_corto: corto };
    }));
  }

  if (m === "GET" && ruta === "pendientes") return json(await pendientes(env, { limite: Math.min(Number(url.searchParams.get("limite") || 20), 100) }));

  if (m === "GET" && ruta === "entidades") {
    const r = await env.DB.prepare("SELECT * FROM master_entities ORDER BY fecha_ultima_actualizacion DESC LIMIT ?").bind(Math.min(Number(url.searchParams.get("limite") || 100), 1000)).all();
    return json(r.results);
  }

  if (m === "GET" && ruta === "export.csv")
    return new Response(csv(await filasEnriquecidas(env)), { headers: { "content-type": "text/csv; charset=utf-8", "content-disposition": 'attachment; filename="entidades_enriquecidas.csv"' } });

  if (m === "GET" && ruta === "campos") return json(CAMPOS_DEFAULT);
  return json({ error: "ruta no encontrada" }, 404);
}

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    const url = new URL(req.url);
    if (url.pathname === "/" || url.pathname === "/index.html") return new Response(DASHBOARD_HTML, { headers: { "content-type": "text/html; charset=utf-8" } });
    if (url.pathname === "/salud") return json({ ok: true });
    if (!url.pathname.startsWith("/api/")) return json({ error: "no encontrado" }, 404);
    if (!autorizado(req, env)) return json({ error: "no autorizado" }, 401);
    try { return await api(req, env, url); }
    catch (e) { return json({ error: String(e) }, 500); }
  },

  /** Cron diario: toma los ZIP nuevos que haya en R2 e investiga pendientes, con topes para controlar el gasto. */
  async scheduled(_ev: ScheduledController, env: Env): Promise<void> {
    if (env.CRON_ACTIVO !== "true") return;
    const zips = Number(env.CRON_ZIPS_POR_DIA || 5), ents = Number(env.CRON_ENTIDADES_POR_DIA || 10);
    await lanzarNuevos(env, zips, true, Math.max(Math.floor(ents / Math.max(zips, 1)), 1));
    const p = await pendientes(env, { limite: 1 });
    if (p.resumen.total_pendientes > 0) await env.INVESTIGADOR.create({ id: `cron-${Date.now().toString(36)}`, params: { limite: ents } });
  },
} satisfies ExportedHandler<Env>;
