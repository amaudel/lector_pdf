/** Validación estructural de RUC ecuatoriano. Informativa: muchos RUC reales recientes no pasan el módulo 11. */
const COEF_PRIVADA = [4, 3, 2, 7, 6, 5, 4, 3, 2];
const COEF_PUBLICA = [3, 2, 7, 6, 5, 4, 3, 2];

function modulo11(d: number[], coef: number[], verificador: number): boolean {
  const suma = d.reduce((a, x, i) => a + x * coef[i], 0);
  let esperado = 11 - (suma % 11);
  if (esperado === 11) esperado = 0;
  return esperado !== 10 && esperado === verificador;
}

function modulo10(d: number[]): number {
  let suma = 0;
  d.forEach((x, i) => { const p = x * (i % 2 === 0 ? 2 : 1); suma += p > 9 ? p - 9 : p; });
  return (10 - (suma % 10)) % 10;
}

export function validarRuc(entrada: unknown): { valido: boolean; tipo: string | null; motivo: string } {
  const ruc = String(entrada ?? "").replace(/\D/g, "");
  if (ruc.length !== 13) return { valido: false, tipo: null, motivo: "No tiene 13 dígitos" };
  const d = [...ruc].map(Number);
  const prov = Number(ruc.slice(0, 2));
  if (!((prov >= 1 && prov <= 24) || prov === 30)) return { valido: false, tipo: null, motivo: `Código de provincia inválido (${ruc.slice(0, 2)})` };
  const t = d[2];
  let ok: boolean, tipo: string;
  if (t === 9) { ok = modulo11(d.slice(0, 9), COEF_PRIVADA, d[9]) && Number(ruc.slice(10)) >= 1; tipo = "SOCIEDAD_PRIVADA"; }
  else if (t === 6) { ok = modulo11(d.slice(0, 8), COEF_PUBLICA, d[8]) && Number(ruc.slice(9)) >= 1; tipo = "SOCIEDAD_PUBLICA"; }
  else if (t < 6) { ok = modulo10(d.slice(0, 9)) === d[9] && Number(ruc.slice(10)) >= 1; tipo = "PERSONA_NATURAL"; }
  else return { valido: false, tipo: null, motivo: `Tercer dígito inválido (${t})` };
  return { valido: ok, tipo, motivo: ok ? "OK" : "Dígito verificador no coincide" };
}
