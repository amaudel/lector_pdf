/** Normalizaciones portadas de los scripts Python (5_deduplicate_entities.py y adapters/dataset.py). */

export function sinTildes(s: string): string {
  return s.normalize("NFKD").replace(/[\u0300-\u036f]/g, "");
}

/** normalize_business_name del Paso 5. */
export function normalizarNombre(name: string | null | undefined): string {
  if (!name) return "";
  return name.toUpperCase().replace(/_/g, " ").replace(/["'“”.,;]/g, "").replace(/\s+/g, " ").trim();
}

/** _normalize_for_compare del adapter dataset: sin tildes y solo A-Z0-9. */
export function normalizarComparacion(name: string | null | undefined): string {
  if (!name) return "";
  return sinTildes(name.toUpperCase()).replace(/[^A-Z0-9]/g, "");
}

export const PALABRAS_RUIDO = new Set([
  "CIA", "LTDA", "SA", "SAS", "CA", "EP", "CIALTDA", "S.A.", "C.A.", "S.A.S.",
  "COMPANIA", "COMPAÑIA", "COMPANIAS", "COMPAÑIAS", "LIMITADA", "SOCIEDAD", "ANONIMA",
  "ANÓNIMA", "CORPORACION", "CORPORACIÓN", "GRUPO", "DE", "DEL", "EL", "LA", "LOS",
  "Y", "E", "EN", "LIQUIDACION", "LIQUIDACIÓN", "SUCURSAL", "AGENCIA", "ASOCIACION",
  "CONSORCIO", "SERVICIOS", "PRODUCTOS", "ECUADOR", "NACIONAL", "INTERNACIONAL",
  "SUDAMERICA", "PORTAL",
]);

const CIUDAD_A_PROVINCIA: Record<string, string> = {
  "QUITO": "PICHINCHA", "CUENCA": "AZUAY", "GUAYAQUIL": "GUAYAS", "PORTOVIEJO": "MANABI", "MANTA": "MANABI",
  "LOJA": "LOJA", "AMBATO": "TUNGURAHUA", "MACHALA": "EL ORO", "RIOBAMBA": "CHIMBORAZO", "IBARRA": "IMBABURA",
  "LATACUNGA": "COTOPAXI", "ESMERALDAS": "ESMERALDAS", "BABAHOYO": "LOS RIOS", "QUEVEDO": "LOS RIOS",
  "SANTO DOMINGO": "SANTO DOMINGO DE LOS TSACHILAS", "SANTA ELENA": "SANTA ELENA", "SALINAS": "SANTA ELENA",
  "TULCAN": "CARCHI", "AZOGUES": "CANAR", "GUARANDA": "BOLIVAR", "PUYO": "PASTAZA", "TENA": "NAPO",
  "MACAS": "MORONA SANTIAGO", "ZAMORA": "ZAMORA CHINCHIPE", "NUEVA LOJA": "SUCUMBIOS", "LAGO AGRIO": "SUCUMBIOS",
  "COCA": "ORELLANA", "FRANCISCO DE ORELLANA": "ORELLANA",
};

export function normalizarProvincia(prov: string | null | undefined): string {
  if (!prov) return "";
  const p = sinTildes(prov.trim().toUpperCase());
  return CIUDAD_A_PROVINCIA[p] ?? p;
}

export function compararProvincias(pdf: string | null, db: string | null): "ALTA" | "BAJA" | "SIN_DATO_ORIGEN" | "SIN_DATO_DB" {
  if (!pdf || ["NULL", "NONE", "SIN_DATO"].includes(pdf.toUpperCase())) return "SIN_DATO_ORIGEN";
  const a = normalizarProvincia(pdf), b = normalizarProvincia(db);
  if (!b) return "SIN_DATO_DB";
  return a === b || a.includes(b) || b.includes(a) ? "ALTA" : "BAJA";
}

/** Tokens "núcleo" de un nombre: sin ruido societario y de más de 2 letras. */
export function tokensNucleo(name: string): string[] {
  return name.toUpperCase().replace(/[^A-Z0-9\s]/g, " ").split(/\s+/)
    .filter((t) => t.length > 2 && !PALABRAS_RUIDO.has(t));
}

export function ahora(): string {
  return new Date().toISOString().replace(/\.\d+Z$/, "Z");
}
