import { WorkflowEntrypoint, type WorkflowEvent, type WorkflowStep } from "cloudflare:workers";
import { NonRetryableError } from "cloudflare:workflows";
import { CAMPOS_DEFAULT, cerrarEntidad, pendientes, type Pendiente } from "./agente/store";
import { iteracion, type SalidaHerramienta } from "./agente/investigador";
import type { Env, InvestigadorParams, PipelineParams } from "./env";
import { ahora } from "./norm";
import { deduplicar, type EntidadCruda } from "./pipeline/dedupe";
import { extraerDeTexto, extraerDePaginaEscaneada, type EntidadLLM } from "./pipeline/extract";
import { integrarEnMaestro, type FilaMaestro } from "./pipeline/master";
import { textoPorPagina } from "./pipeline/pdfText";
import { resolverCandidato } from "./pipeline/resolve";
import { base64, extraerPdfs, sha256 } from "./pipeline/unzip";

const REINTENTOS = { retries: { limit: 3, delay: "10 seconds", backoff: "exponential" }, timeout: "10 minutes" } as const;
const MAX_ESCANEADAS_POR_PDF = 8;

const hash = (s: string): string => { let h = 5381; for (const c of s) h = ((h << 5) + h + c.charCodeAt(0)) | 0; return (h >>> 0).toString(36); };

async function enLotes<T, R>(items: T[], n: number, fn: (x: T) => Promise<R>): Promise<R[]> {
  const out: R[] = [];
  for (let i = 0; i < items.length; i += n) out.push(...(await Promise.all(items.slice(i, i + n).map(fn))));
  return out;
}

async function conReintento<T>(fn: () => Promise<T>, veces = 2): Promise<T> {
  let ultimo: unknown;
  for (let i = 0; i <= veces; i++) {
    try { return await fn(); } catch (e) { ultimo = e; await new Promise((r) => setTimeout(r, 1500 * (i + 1))); }
  }
  throw ultimo;
}

/** Bucle del agente investigador sobre una lista de entidades. Cada llamada al modelo es un step durable y reintentable. */
export async function investigarLista(env: Env, step: WorkflowStep, lista: Pendiente[], campos: string[]): Promise<Record<string, number>> {
  const max = Number(env.MAX_ITER_AGENTE || 12);
  const resumen: Record<string, number> = { investigadas: 0, ENCONTRADO: 0, NO_ENCONTRADO: 0, REVISION_MANUAL: 0 };
  for (const p of lista) {
    const id = hash(p.clave);
    let previo: { respId?: string; entrada?: SalidaHerramienta[] } = {};
    for (let i = 0; i < max; i++) {
      const r = await step.do(`investigar-${id}-${i}`, { ...REINTENTOS, timeout: "8 minutes" }, async () => iteracion(env, p, campos, previo));
      previo = { respId: r.respId, entrada: r.siguiente };
      if (r.terminado) break;
    }
    const estado = await step.do(`cierre-${id}`, async () => {
      const st = await env.DB.prepare("SELECT estado FROM agent_entity_status WHERE clave = ?").bind(p.clave).first<{ estado: string }>();
      if (st && ["ENCONTRADO", "NO_ENCONTRADO", "REVISION_MANUAL"].includes(st.estado)) return st.estado;
      // El agente terminó sin cerrar: no se pierde el trabajo, queda para una persona.
      await cerrarEntidad(env, p.clave, p.razon_social, "REVISION_MANUAL", "El agente terminó sin poder cerrar la entidad como ENCONTRADO (sin RUC verificado con confianza ALTA, o límite de iteraciones). Revisar agent_findings y agent_research_log.");
      return "REVISION_MANUAL";
    });
    resumen.investigadas++;
    resumen[estado] = (resumen[estado] ?? 0) + 1;
  }
  return resumen;
}

export class PipelineWorkflow extends WorkflowEntrypoint<Env, PipelineParams> {
  async run(event: WorkflowEvent<PipelineParams>, step: WorkflowStep) {
    const env = this.env;
    const { zip, investigar, limite, forzar } = event.payload;
    const lote = zip.replace(/\.zip$/i, "");
    const zipLote = `${lote}.zip`;
    const resumen: Record<string, unknown> = { zip };

    // Lotes nuevos llegan todo el tiempo: si el mismo contenido ya se procesó con otro nombre, no se paga dos veces.
    const dup = await step.do("duplicado", async () => {
      const obj = await env.ARCHIVOS.get(`input/${zip}`);
      if (!obj) throw new NonRetryableError(`No existe input/${zip} en R2`);
      const sha = await sha256(new Uint8Array(await obj.arrayBuffer()));
      const otro = await env.DB.prepare("SELECT lote FROM lotes WHERE zip_sha256 = ? AND lote != ? AND estado = 'COMPLETADO' LIMIT 1").bind(sha, zipLote).first<{ lote: string }>();
      return { sha, igualA: otro?.lote ?? null };
    });
    if (dup.igualA && !forzar) {
      await step.do("marcar-duplicado", async () => {
        await env.DB.prepare(`INSERT INTO lotes (lote, zip_key, zip_sha256, estado, workflow_id, fecha_inicio, fecha_fin, resumen) VALUES (?,?,?,?,?,?,?,?)
          ON CONFLICT(lote) DO UPDATE SET estado='DUPLICADO', zip_sha256=excluded.zip_sha256, resumen=excluded.resumen, fecha_fin=excluded.fecha_fin`)
          .bind(zipLote, `input/${zip}`, dup.sha, "DUPLICADO", event.instanceId, ahora(), ahora(), JSON.stringify({ duplicado_de: dup.igualA })).run();
      });
      return { zip, estado: "DUPLICADO", duplicado_de: dup.igualA };
    }

    await step.do("inicio", async () => {
      await env.DB.batch([
        env.DB.prepare("DELETE FROM entidades_extraidas WHERE lote = ?").bind(zipLote),
        env.DB.prepare("DELETE FROM paginas WHERE lote = ?").bind(zipLote),
        env.DB.prepare("DELETE FROM documentos WHERE lote = ?").bind(zipLote),
        env.DB.prepare("DELETE FROM candidatos WHERE lote = ?").bind(zipLote),
        env.DB.prepare(`INSERT INTO lotes (lote, zip_key, zip_sha256, estado, workflow_id, fecha_inicio) VALUES (?,?,?,?,?,?)
          ON CONFLICT(lote) DO UPDATE SET estado='EN_PROCESO', zip_sha256=excluded.zip_sha256, workflow_id=excluded.workflow_id, fecha_inicio=excluded.fecha_inicio, fecha_fin=NULL, resumen=NULL`)
          .bind(zipLote, `input/${zip}`, dup.sha, "EN_PROCESO", event.instanceId, ahora()),
      ]);
    });

    // Paso 1: descomprimir + inventario
    const docs = await step.do("descomprimir", REINTENTOS, async () => {
      const obj = await env.ARCHIVOS.get(`input/${zip}`);
      if (!obj) throw new NonRetryableError(`No existe input/${zip} en R2`);
      let r;
      try { r = extraerPdfs(new Uint8Array(await obj.arrayBuffer())); }
      catch (e) { throw new NonRetryableError(`ZIP inválido o corrupto: ${e}`); }
      const lista: { id: string; nombre: string; ruta: string; key: string }[] = [];
      const filas: D1PreparedStatement[] = [];
      for (const pdf of r.pdfs) {
        const id = crypto.randomUUID(), key = `pdf/${lote}/${id}.pdf`;
        await env.ARCHIVOS.put(key, pdf.datos, { httpMetadata: { contentType: "application/pdf" } });
        filas.push(env.DB.prepare("INSERT INTO documentos (id, lote, archivo_origen, ruta_en_zip, r2_key, tamano, sha256) VALUES (?,?,?,?,?,?,?)")
          .bind(id, zipLote, pdf.nombre, pdf.ruta, key, pdf.datos.length, await sha256(pdf.datos)));
        lista.push({ id, nombre: pdf.nombre, ruta: pdf.ruta, key });
      }
      for (let i = 0; i < filas.length; i += 90) await env.DB.batch(filas.slice(i, i + 90));
      return { lista, encontrados: r.archivosEncontrados, ignorados: r.ignorados, errores: r.errores };
    });
    resumen.pdfs = docs.lista.length; resumen.archivos_ignorados = docs.ignorados; resumen.errores_zip = docs.errores.length;
    if (!docs.lista.length) {
      await step.do("fin-sin-pdfs", async () => {
        await env.DB.prepare("UPDATE lotes SET estado='SIN_PDFS', fecha_fin=?, resumen=? WHERE lote=?").bind(ahora(), JSON.stringify(resumen), zipLote).run();
      });
      return resumen;
    }

    // Paso 2: texto por página
    for (const d of docs.lista) {
      await step.do(`texto-${d.id}`, REINTENTOS, async () => {
        const obj = await env.ARCHIVOS.get(d.key);
        if (!obj) throw new NonRetryableError(`Falta ${d.key}`);
        let paginas;
        try { paginas = await textoPorPagina(new Uint8Array(await obj.arrayBuffer())); }
        catch (e) { paginas = [{ pagina: 1, estado: "ERROR" as const, texto: String(e).slice(0, 200) }]; }
        await env.DB.batch([
          ...paginas.map((p) => env.DB.prepare("INSERT OR REPLACE INTO paginas (lote, id_documento, archivo_origen, pagina, estado, texto) VALUES (?,?,?,?,?,?)")
            .bind(zipLote, d.id, d.nombre, p.pagina, p.estado, p.texto)),
          env.DB.prepare("UPDATE documentos SET paginas = ? WHERE id = ?").bind(paginas.length, d.id),
        ]);
      });
    }

    // Paso 4: entidades con OpenAI (gpt-4o-mini)
    let errores_api = 0, paginas_analizadas = 0;
    for (const d of docs.lista) {
      const r = await step.do(`entidades-${d.id}`, REINTENTOS, async () => {
        const pags = (await env.DB.prepare("SELECT pagina, estado, texto FROM paginas WHERE id_documento = ? ORDER BY pagina").bind(d.id).all<{ pagina: number; estado: string; texto: string }>()).results;
        const conTexto = pags.filter((p) => p.estado === "OK");
        const escaneadas = pags.filter((p) => p.estado === "SIN_TEXTO").slice(0, MAX_ESCANEADAS_POR_PDF);
        let pdfB64 = "";
        if (escaneadas.length) {
          const obj = await env.ARCHIVOS.get(d.key);
          if (obj) pdfB64 = base64(new Uint8Array(await obj.arrayBuffer()));
        }
        let fallos = 0;
        const hallazgos: { pagina: number; ents: EntidadLLM[] }[] = [];
        const trabajos = [
          ...conTexto.map((p) => ({ pagina: p.pagina, run: () => extraerDeTexto(env, p.texto) })),
          ...(pdfB64 ? escaneadas.map((p) => ({ pagina: p.pagina, run: () => extraerDePaginaEscaneada(env, pdfB64, d.nombre, p.pagina) })) : []),
        ];
        await enLotes(trabajos, 5, async (t) => {
          try { hallazgos.push({ pagina: t.pagina, ents: await conReintento(t.run) }); } catch { fallos++; }
        });
        // Si TODAS las páginas fallaron, probablemente es la API (clave/cuota): que el step se reintente en vez de perder el documento.
        if (trabajos.length && fallos === trabajos.length) throw new Error("Todas las llamadas a OpenAI fallaron para este documento");
        const filas = hallazgos.flatMap((h) => h.ents.map((e) => env.DB.prepare(
          `INSERT INTO entidades_extraidas (lote, id_documento, archivo_origen, pagina, razon_social_original, ruc_detectado, provincia, tipo, fragmento, confianza, estado_entidad)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)`).bind(zipLote, d.id, d.nombre, h.pagina, e.razon_social_original ?? null, e.ruc_detectado_en_texto ?? null,
          e.provincia_mencionada ?? null, e.tipo_entidad_detectada ?? null, e.fragmento_evidencia ?? null, e.nivel_confianza_extraccion ?? null, e.estado_entidad ?? null)));
        for (let i = 0; i < filas.length; i += 90) await env.DB.batch(filas.slice(i, i + 90));
        return { analizadas: trabajos.length, fallos };
      });
      errores_api += r.fallos; paginas_analizadas += r.analizadas;
    }
    resumen.paginas_analizadas = paginas_analizadas; resumen.errores_api = errores_api;

    // Pasos 5, 7 y 7.5: deduplicar, resolver y auditar (apto / no apto)
    const cand = await step.do("candidatos", REINTENTOS, async () => {
      const crudas = (await env.DB.prepare("SELECT lote, archivo_origen, pagina, razon_social_original, ruc_detectado, provincia, tipo, fragmento, estado_entidad FROM entidades_extraidas WHERE lote = ?")
        .bind(zipLote).all<EntidadCruda>()).results;
      const candidatos = deduplicar(crudas);
      await env.DB.prepare("DELETE FROM candidatos WHERE lote = ?").bind(zipLote).run();
      const conteo: Record<string, number> = {};
      const filas: D1PreparedStatement[] = [];
      for (const c of candidatos) {
        const r = await resolverCandidato(env, c);
        conteo[r.estado_resolucion] = (conteo[r.estado_resolucion] ?? 0) + 1;
        filas.push(env.DB.prepare(
          `INSERT INTO candidatos (lote, clave, razon_social_original, razon_social_normalizada, tipo_entidad, provincia, ruc_detectado, menciones, archivos, paginas, fragmentos,
             provincia_consistente, tipo_consistente, confianza, estado_candidato, ruc_final, fuente_ruc, estado_resolucion, coincidencia_nombre, coincidencia_provincia,
             provincia_oficial, sucursal_azuay, observaciones, apto_maestro) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`)
          .bind(zipLote, c.clave, c.razon_social_original, c.razon_social_normalizada, c.tipo_entidad, c.provincia, c.ruc_detectado, c.menciones,
            JSON.stringify(c.archivos), JSON.stringify(c.paginas), JSON.stringify(c.fragmentos), c.provincia_consistente, c.tipo_consistente, c.confianza,
            c.estado_candidato, r.ruc_final, r.ruc_final ? (c.ruc_detectado ? "TEXTO_PDF" : r.fuente_consultada) : null, r.estado_resolucion,
            r.coincidencia_nombre, r.coincidencia_provincia, r.provincia_oficial, r.sucursal_azuay, r.observaciones, r.apto ? 1 : 0));
      }
      for (let i = 0; i < filas.length; i += 90) await env.DB.batch(filas.slice(i, i + 90));
      return { total: candidatos.length, estados: conteo, aptos: candidatos.length ? (await env.DB.prepare("SELECT COUNT(*) AS n FROM candidatos WHERE lote = ? AND apto_maestro = 1").bind(zipLote).first<{ n: number }>())!.n : 0 };
    });
    resumen.candidatos = cand.total; resumen.estados = cand.estados; resumen.aptos_para_maestro = cand.aptos;

    // Paso 8: maestro
    resumen.maestro = await step.do("maestro", REINTENTOS, async () => {
      const aptos = (await env.DB.prepare("SELECT * FROM candidatos WHERE lote = ? AND apto_maestro = 1").bind(zipLote).all<any>()).results;
      const filas: FilaMaestro[] = aptos.map((r) => ({
        ruc_final: r.ruc_final, razon_social_original: r.razon_social_original, razon_social_normalizada: r.razon_social_normalizada, tipo_entidad: r.tipo_entidad,
        provincia: r.provincia, provincia_oficial: r.provincia_oficial, estado_resolucion: r.estado_resolucion, fuente_ruc: r.fuente_ruc, lote: zipLote,
        menciones: r.menciones, archivos: JSON.parse(r.archivos || "[]"), paginas: JSON.parse(r.paginas || "[]"), fragmentos: JSON.parse(r.fragmentos || "[]"),
      }));
      return integrarEnMaestro(env, lote, filas, forzar);
    });

    // Agente investigador sobre lo que quedó sin RUC
    if (investigar && limite > 0) {
      const lista = await step.do("pendientes", async () => (await pendientes(env, { lote: zipLote, limite })).lista);
      resumen.agente = lista.length ? await investigarLista(env, step, lista, CAMPOS_DEFAULT) : { investigadas: 0 };
    }

    await step.do("fin", async () => {
      await env.DB.prepare("UPDATE lotes SET estado='COMPLETADO', fecha_fin=?, resumen=? WHERE lote=?").bind(ahora(), JSON.stringify(resumen), zipLote).run();
    });
    return resumen;
  }
}

export class InvestigadorWorkflow extends WorkflowEntrypoint<Env, InvestigadorParams> {
  async run(event: WorkflowEvent<InvestigadorParams>, step: WorkflowStep) {
    const { limite, claves } = event.payload;
    const lista = await step.do("pendientes", async () => (await pendientes(this.env, { limite, claves })).lista);
    if (!lista.length) return { investigadas: 0 };
    return investigarLista(this.env, step, lista, CAMPOS_DEFAULT);
  }
}
