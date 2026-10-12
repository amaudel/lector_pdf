import type { Env } from "../env";
import { compararProvincias, normalizarComparacion, PALABRAS_RUIDO, tokensNucleo } from "../norm";
import type { Candidato } from "./dedupe";

export interface Resolucion {
  ruc_final: string | null; estado_resolucion: string; fuente_consultada: string;
  coincidencia_nombre: string; coincidencia_provincia: string; provincia_oficial: string | null;
  sucursal_azuay: string; observaciones: string;
}
interface FilaCatalogo { ruc: string; razon_social: string; provincia: string | null; fuente: string }

const APTOS = ["RUC_EXTRAIDO_DEL_PDF", "COINCIDENCIA_DATASET_LOCAL_ALTA", "VALIDADO_DATASET_OFICIAL", "VALIDADO_EXTERNAMENTE"];
export const esApto = (estado: string): boolean => APTOS.includes(estado);

function nombreValido(consulta: string, enDb: string): boolean {
  const q = tokensNucleo(consulta), d = tokensNucleo(enDb);
  if (!q.length) return false;
  return q.some((qt) => d.some((dt) => qt.includes(dt) || dt.includes(qt)));
}

async function sucursalAzuay(env: Env, ruc: string | null): Promise<string> {
  if (!ruc) return "NO";
  const r = await env.DB.prepare("SELECT COUNT(*) AS n FROM catalogo WHERE ruc = ? AND provincia LIKE '%AZUAY%'").bind(ruc).first<{ n: number }>();
  return (r?.n ?? 0) > 0 ? "SI" : "NO";
}

async function resultado(env: Env, ruc: string | null, estado: string, nombre: string, prov: string, obs: string, provOficial: string | null = null): Promise<Resolucion> {
  return {
    ruc_final: ruc, estado_resolucion: estado, fuente_consultada: "CATALOGO_UNIFICADO_LOCAL", coincidencia_nombre: nombre,
    coincidencia_provincia: prov, provincia_oficial: provOficial, sucursal_azuay: await sucursalAzuay(env, ruc), observaciones: obs,
  };
}

/** Portado de adapters/dataset.py: busca en el catálogo (D1 + FTS5) y decide por nombre y provincia. */
export async function resolverEnCatalogo(env: Env, nombre: string, provincia: string | null): Promise<Resolucion> {
  const limpio = (nombre || "").trim().toUpperCase();
  if (!limpio) return resultado(env, null, "SIN_RESULTADO_DATASET", "N/A", "N/A", "Nombre vacío o inválido.");
  const objetivo = normalizarComparacion(limpio);
  const palabras = limpio.replace(/[^\w\s]/g, " ").split(/\s+/).filter(Boolean);
  let clave = palabras.filter((w) => !PALABRAS_RUIDO.has(w)).sort((a, b) => b.length - a.length).slice(0, 3);
  if (!clave.length) clave = palabras.filter((w) => w.length > 2).slice(0, 3);

  let candidatos: FilaCatalogo[] = [];
  if (clave.length) {
    try {
      const match = clave.map((w) => `"${w.replace(/"/g, "")}"`).join(" ");
      candidatos = (await env.DB.prepare(
        `SELECT c.ruc, c.razon_social, c.provincia, c.fuente FROM catalogo_fts f JOIN catalogo c ON c.rowid = f.rowid
         WHERE catalogo_fts MATCH ? LIMIT 150`).bind(match).all<FilaCatalogo>()).results;
    } catch (e) {
      return resultado(env, null, "SIN_RESULTADO_DATASET", "N/A", "N/A", `Catálogo no disponible en D1: ${e}`);
    }
  }
  const exactos = candidatos.filter((r) => {
    const db = normalizarComparacion(r.razon_social);
    return objetivo === db || db.includes(objetivo) || objetivo.includes(db);
  });
  const provDe = (r: FilaCatalogo): string => (r.provincia ? r.provincia.toUpperCase() : "");

  if (exactos.length === 1) {
    const r = exactos[0];
    return resultado(env, r.ruc, "COINCIDENCIA_DATASET_LOCAL_ALTA", "ALTA", compararProvincias(provincia, provDe(r)), `Coincidencia exacta en catálogo (${r.fuente}).`, provDe(r));
  }
  if (exactos.length > 1) {
    const porProv = exactos.filter((r) => compararProvincias(provincia, provDe(r)) === "ALTA");
    if (porProv.length === 1) return resultado(env, porProv[0].ruc, "COINCIDENCIA_DATASET_LOCAL_ALTA", "ALTA", "ALTA", `Múltiples empresas idénticas: Desempate por provincia (${porProv[0].fuente}).`, provDe(porProv[0]));
    if (porProv.length > 1) return resultado(env, null, "AMBIGUO_DATASET_LOCAL", "ALTA", "AMBIGUO", `Existen ${porProv.length} empresas con idéntico nombre EN LA MISMA PROVINCIA.`);
    return resultado(env, null, "AMBIGUO_DATASET_LOCAL", "ALTA", "AMBIGUO", `Existen ${exactos.length} empresas con idéntico nombre en diferentes provincias.`);
  }
  if (candidatos.length === 1) {
    const r = candidatos[0];
    if (nombreValido(limpio, r.razon_social)) return resultado(env, r.ruc, "COINCIDENCIA_DATASET_LOCAL_MEDIA", "MEDIA", "N/A", `Búsqueda aproximada exitosa (${r.fuente}).`, provDe(r));
    return resultado(env, null, "SIN_RESULTADO_DATASET", "BAJA", "N/A", "El candidato único devuelto por FTS no coincide en palabras clave.");
  }
  if (candidatos.length > 1) {
    const validos = candidatos.filter((r) => nombreValido(limpio, r.razon_social));
    if (validos.length === 1) return resultado(env, validos[0].ruc, "COINCIDENCIA_DATASET_LOCAL_MEDIA", "MEDIA", "N/A", `Búsqueda aproximada única tras depuración (${validos[0].fuente}).`, provDe(validos[0]));
    return resultado(env, null, "AMBIGUO_DATASET_LOCAL", "MEDIA", "N/A", "Búsqueda aproximada: Múltiples opciones parecidas detectadas.");
  }
  return resultado(env, null, "SIN_RESULTADO_DATASET", "BAJA", "N/A", "A pesar de buscar en TODO el catálogo nacional, no hubo rastro ni parecido.");
}

/** Paso 7: Ruta A (RUC en el PDF) o Ruta B (catálogo). Devuelve las columnas de resolución del candidato. */
export async function resolverCandidato(env: Env, c: Candidato): Promise<Resolucion & { apto: boolean }> {
  if (c.estado_candidato !== "LISTA_PARA_BUSQUEDA") {
    return {
      ruc_final: null, estado_resolucion: "REVISION_MANUAL", fuente_consultada: "DEDUPLICADOR_INTERNO", coincidencia_nombre: "N/A",
      coincidencia_provincia: "N/A", provincia_oficial: null, sucursal_azuay: "NO",
      observaciones: `Derivado a revisión por estado inicial de limpieza: ${c.estado_candidato}`, apto: false,
    };
  }
  if (c.ruc_detectado) {
    return {
      ruc_final: c.ruc_detectado, estado_resolucion: "RUC_EXTRAIDO_DEL_PDF", fuente_consultada: "DEDUPLICADOR_INTERNO",
      coincidencia_nombre: "N/A", coincidencia_provincia: "N/A", provincia_oficial: null, sucursal_azuay: "NO",
      observaciones: "RUC capturado textualmente y consolidado sin necesidad de enriquecimiento externo.", apto: true,
    };
  }
  const r = await resolverEnCatalogo(env, c.razon_social_normalizada, c.provincia);
  return { ...r, apto: esApto(r.estado_resolucion) };
}
