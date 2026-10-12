import type { Env } from "../env";
import { ahora } from "../norm";

export interface FilaMaestro {
  ruc_final: string; razon_social_original: string | null; razon_social_normalizada: string; tipo_entidad: string | null;
  provincia: string | null; provincia_oficial: string | null; estado_resolucion: string; fuente_ruc: string | null;
  lote: string; menciones: number; archivos: string[]; paginas: number[]; fragmentos: string[];
}

/** Sentencias INSERT OR IGNORE de evidencia (misma lógica de empate de índices que el Paso 8 local). */
export function sentenciasEvidencia(
  env: Env, ruc: string, lote: string, o: { archivos: string[]; paginas: number[]; fragmentos: string[] },
  estado: string, fuenteRuc: string, ts: string,
): D1PreparedStatement[] {
  const n = Math.max(o.archivos.length, o.paginas.length, o.fragmentos.length, 1);
  const pick = <T>(a: T[], i: number, def: T): T => (i < a.length ? a[i] : a.length ? a[a.length - 1] : def);
  const out: D1PreparedStatement[] = [];
  for (let i = 0; i < n; i++) {
    const p = pick<number | string>(o.paginas, i, 0);
    out.push(env.DB.prepare(
      `INSERT OR IGNORE INTO master_evidence (ruc, lote, archivo_origen, pagina_pdf, fragmento_evidencia, estado_resolucion_origen, fecha_ingesta, fuente_ruc)
       VALUES (?,?,?,?,?,?,?,?)`).bind(ruc, lote, pick(o.archivos, i, "Desconocido"), /^\d+$/.test(String(p)) ? Number(p) : 0,
      String(pick(o.fragmentos, i, "")), estado, ts, fuenteRuc));
  }
  return out;
}

export async function revertirLote(env: Env, loteBase: string): Promise<{ evidencias: number; entidadesPurgadas: number }> {
  const like = `${loteBase}%`;
  const impactos = (await env.DB.prepare("SELECT ruc, COUNT(*) AS n FROM master_evidence WHERE lote LIKE ? GROUP BY ruc").bind(like).all<{ ruc: string; n: number }>()).results;
  const stmts: D1PreparedStatement[] = [];
  for (const { ruc, n } of impactos) {
    if (!ruc) continue;
    stmts.push(env.DB.prepare("UPDATE master_entities SET total_menciones = total_menciones - ?, total_lotes_detectado = total_lotes_detectado - 1 WHERE ruc = ?").bind(n, ruc));
    stmts.push(env.DB.prepare("DELETE FROM master_entities WHERE ruc = ? AND total_lotes_detectado <= 0").bind(ruc));
  }
  stmts.push(env.DB.prepare("DELETE FROM master_evidence WHERE lote LIKE ?").bind(like));
  stmts.push(env.DB.prepare("DELETE FROM processed_batches WHERE lote_base = ?").bind(loteBase));
  const res = await env.DB.batch(stmts);
  return { evidencias: res[res.length - 2].meta.changes ?? 0, entidadesPurgadas: 0 };
}

/** Paso 8: integra al maestro, de forma atómica e idempotente por lote. */
export async function integrarEnMaestro(env: Env, loteBase: string, filas: FilaMaestro[], forzar: boolean): Promise<Record<string, string | number>> {
  const previo = await env.DB.prepare("SELECT fecha_procesamiento FROM processed_batches WHERE lote_base = ?").bind(loteBase).first<{ fecha_procesamiento: string }>();
  if (previo) {
    if (!forzar) return { estado: "OMITIDO_LOTE_YA_INTEGRADO", fecha: previo.fecha_procesamiento };
    await revertirLote(env, loteBase);
  }
  const ts = ahora();
  const metricas = { leidos: 0, insertados: 0, actualizados: 0, rechazados: 0 };
  const rucs = [...new Set(filas.map((f) => (f.ruc_final || "").trim()).filter(Boolean))];
  const existentes = new Set<string>();
  for (let i = 0; i < rucs.length; i += 80) {
    const trozo = rucs.slice(i, i + 80);
    const r = await env.DB.prepare(`SELECT ruc FROM master_entities WHERE ruc IN (${trozo.map(() => "?").join(",")})`).bind(...trozo).all<{ ruc: string }>();
    r.results.forEach((x) => existentes.add(x.ruc));
  }
  const stmts: D1PreparedStatement[] = [];
  for (const f of filas) {
    metricas.leidos++;
    const ruc = (f.ruc_final || "").trim();
    if (!ruc || ["none", "null"].includes(ruc.toLowerCase())) { metricas.rechazados++; continue; }
    if (existentes.has(ruc)) {
      stmts.push(env.DB.prepare("UPDATE master_entities SET total_lotes_detectado = total_lotes_detectado + 1, total_menciones = total_menciones + ?, fecha_ultima_actualizacion = ? WHERE ruc = ?").bind(f.menciones, ts, ruc));
      metricas.actualizados++;
    } else {
      stmts.push(env.DB.prepare(
        `INSERT INTO master_entities (ruc, razon_social_canonica, razon_social_normalizada, tipo_entidad, provincia_preferida, estado_resolucion_master,
           fuente_primaria, fecha_primera_aparicion, fecha_ultima_actualizacion, total_lotes_detectado, total_menciones) VALUES (?,?,?,?,?,?,?,?,?,?,?)`)
        .bind(ruc, f.razon_social_original || "DESCONOCIDA", f.razon_social_normalizada || "DESCONOCIDA", f.tipo_entidad || "DESCONOCIDO",
          f.provincia_oficial || f.provincia || "DESCONOCIDA", f.estado_resolucion, f.fuente_ruc || "DESCONOCIDO", ts, ts, 1, f.menciones));
      existentes.add(ruc);
      metricas.insertados++;
    }
    stmts.push(...sentenciasEvidencia(env, ruc, f.lote, f, f.estado_resolucion, f.fuente_ruc || "DESCONOCIDO", ts));
  }
  stmts.push(env.DB.prepare(
    "INSERT OR REPLACE INTO processed_batches (lote_base, fecha_procesamiento, total_registros_leidos, total_insertados, total_actualizados, referencia_archivo) VALUES (?,?,?,?,?,?)")
    .bind(loteBase, ts, metricas.leidos, metricas.insertados, metricas.actualizados, `candidatos:${loteBase}`));
  for (let i = 0; i < stmts.length; i += 90) await env.DB.batch(stmts.slice(i, i + 90));
  return { estado: forzar && previo ? "REPROCESADO" : "NUEVO", ...metricas };
}
