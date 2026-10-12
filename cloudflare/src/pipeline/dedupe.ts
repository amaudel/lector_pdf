import { normalizarNombre } from "../norm";

export interface EntidadCruda {
  lote: string; archivo_origen: string | null; pagina: number | null; razon_social_original: string | null;
  ruc_detectado: string | null; provincia: string | null; tipo: string | null; fragmento: string | null; estado_entidad: string | null;
}
export interface Candidato {
  lote: string; clave: string; razon_social_original: string | null; razon_social_normalizada: string;
  tipo_entidad: string | null; provincia: string | null; ruc_detectado: string | null; menciones: number;
  archivos: string[]; paginas: number[]; fragmentos: string[];
  provincia_consistente: string; tipo_consistente: string; confianza: string; estado_candidato: string;
}

// Instituciones emisoras / de control que NO son la entidad investigada (Paso 5).
const FILTRO_RUIDO = [
  "INSTITUTO ECUATORIANO DE SEGURIDAD SOCIAL", "SERVICIO DE RENTAS INTERNAS",
  "SUPERINTENDENCIA DE COMPAÑÍAS VALORES Y SEGUROS", "SUPERINTENDENCIA DE COMPAÑIAS VALORES Y SEGUROS",
  "SUPERINTENDENCIA DE COMPANIAS VALORES Y SEGUROS", "SUPERINTENDENCIA DE COMPAÑÍAS", "SUPERINTENDENCIA DE COMPAÑIAS",
  "SUPERINTENDENCIA DE COMPANIAS", "SUPERCIAS", "SUPER DE COMPAÑÍAS", "SUPER DE COMPAÑIAS", "SUPERINTENDENCIA DE BANCOS",
  "CONTRALORÍA GENERAL DEL ESTADO", "CONTRALORIA GENERAL DEL ESTADO", "INTENDENCIA REGIONAL",
  "INTENDENCIA DE COMPAÑÍAS", "INTENDENCIA DE COMPAÑIAS", "INTENDENCIA DE COMPANIAS", "SUPERINTENDENCIA", "INTENDENCIA",
  "REGISTRO MERCANTIL", "SERVICIO NACIONAL DE CONTRATACIÓN PÚBLICA", "SERVICIO NACIONAL DE CONTRATACION PUBLICA", "SERCOP",
];
const NOMBRES_RUIDO = new Set(["IESS", "SRI", "SERVICIO DE RENTAS INTERNAS SRI", "INSTITUTO ECUATORIANO DE SEGURIDAD SOCIAL IESS",
  "SUPERCIAS", "CONTRALORIA", "REGISTRO MERCANTIL", "SERCOP"]);
const PLACEHOLDERS = new Set(["NONE", "NULL", "NOME", "UNKNOWN", "DESCONOCIDA", "DESCONOCIDO", "SIN DATO", "SIN_DATO", "NO DISPONIBLE",
  "COMPAÑIA", "COMPANIA", "COMPANIAS", "COMPAÑIAS", "EMPRESA", "EMPRESAS", "SOCIEDAD", "ASOCIACION", "ASOCIACIÓN", "CONSORCIO"]);
const PREFIJOS_PLACEHOLDER = ["NONE ", "NULL ", "NOME ", "UNKNOWN ", "DESCONOCIDA ", "DESCONOCIDO ", "SIN DATO "];

function esRuido(norm: string): boolean {
  if (FILTRO_RUIDO.some((r) => norm.includes(r)) || NOMBRES_RUIDO.has(norm)) return true;
  return PLACEHOLDERS.has(norm) || PREFIJOS_PLACEHOLDER.some((p) => norm.startsWith(p)) ||
    norm.includes("MASIVA") || norm.startsWith("SCVS") || norm.replace(/ /g, "").startsWith("SCVS") || norm.length < 3;
}

/** RUC válido por forma: 13 dígitos, termina en 001, provincia 01-24 o 30. */
export function limpiarRuc(ruc: string | null | undefined): string | null {
  if (!ruc) return null;
  const c = String(ruc).replace(/\D/g, "");
  if (c.length !== 13 || !c.endsWith("001")) return null;
  const p = Number(c.slice(0, 2));
  return (p >= 1 && p <= 24) || p === 30 ? c : null;
}

function agregar<T>(a: T[], v: T | null | undefined): void {
  if (v !== null && v !== undefined && (v as unknown) !== "" && !a.includes(v)) a.push(v);
}

/** Paso 5: depura, hereda RUC entre menciones del mismo nombre y agrupa en candidatos únicos. */
export function deduplicar(entidades: EntidadCruda[]): Candidato[] {
  const crudas: (EntidadCruda & { norm: string; ruc: string | null })[] = [];
  for (const e of entidades) {
    if (e.estado_entidad === "SIN_ENTIDAD_CLARA") continue;
    const norm = normalizarNombre(e.razon_social_original);
    if (esRuido(norm)) continue;
    crudas.push({ ...e, norm, ruc: limpiarRuc(e.ruc_detectado) });
  }
  const nombreARuc = new Map<string, string>();
  for (const e of crudas) if (e.ruc && e.norm && !nombreARuc.has(e.norm)) nombreARuc.set(e.norm, e.ruc);

  type G = {
    lote: string; orig: string | null; norm: string; ruc: string | null; menciones: number; tipos: string[]; provs: string[];
    archivos: string[]; paginas: number[]; frags: string[];
  };
  const grupos = new Map<string, G>();
  for (const e of crudas) {
    const ruc = e.ruc ?? nombreARuc.get(e.norm) ?? null;
    const clave = ruc ? `RUC:${ruc}` : `NAME:${e.norm}`;
    let g = grupos.get(clave);
    if (!g) {
      g = { lote: e.lote, orig: e.razon_social_original, norm: e.norm, ruc, menciones: 0, tipos: [], provs: [], archivos: [], paginas: [], frags: [] };
      grupos.set(clave, g);
    }
    g.menciones++;
    agregar(g.tipos, e.tipo); agregar(g.provs, e.provincia); agregar(g.archivos, e.archivo_origen); agregar(g.paginas, e.pagina);
    if (e.fragmento && !g.frags.includes(e.fragmento) && g.frags.length < 3) g.frags.push(e.fragmento);
  }
  const consistencia = (a: unknown[]) => (a.length === 1 ? "SI" : a.length > 1 ? "NO" : "SIN_DATO");
  return [...grupos.entries()].map(([clave, g]) => {
    const confianza = g.ruc ? "ALTA" : g.norm ? (g.menciones >= 2 ? "MEDIA" : "BAJA") : "BAJA";
    return {
      lote: g.lote, clave, razon_social_original: g.orig, razon_social_normalizada: g.norm,
      tipo_entidad: g.tipos[0] ?? null, provincia: g.provs[0] ?? null, ruc_detectado: g.ruc, menciones: g.menciones,
      archivos: g.archivos, paginas: g.paginas.sort((a, b) => a - b), fragmentos: g.frags,
      provincia_consistente: consistencia(g.provs), tipo_consistente: consistencia(g.tipos),
      confianza, estado_candidato: g.norm ? "LISTA_PARA_BUSQUEDA" : "DESCARTAR",
    };
  });
}
