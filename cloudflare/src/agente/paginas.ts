import { textoPorPagina } from "../pipeline/pdfText";

export interface Lectura { ok: boolean; texto: string; error?: string }

const MAX_BYTES = 3_000_000;

function urlPermitida(u: string, permitirLocal = false): URL | null {
  let url: URL;
  try { url = new URL(u); } catch { return null; }
  if (!["http:", "https:"].includes(url.protocol)) return null;
  const h = url.hostname.toLowerCase();
  if (permitirLocal && (h === "127.0.0.1" || h === "localhost")) return url;
  if (h === "localhost" || h.endsWith(".local") || h.endsWith(".internal") || /^[\d.]+$/.test(h) || h.includes(":")) return null;
  return url;
}

function htmlATexto(html: string): string {
  return html
    .replace(/<(script|style|noscript|svg)[\s\S]*?<\/\1>/gi, " ")
    .replace(/<!--[\s\S]*?-->/g, " ")
    .replace(/<(br|\/p|\/div|\/li|\/tr|\/h\d)\s*>/gi, "\n")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ").replace(/&amp;/g, "&").replace(/&quot;/g, '"').replace(/&#39;/g, "'")
    .replace(/&lt;/g, "<").replace(/&gt;/g, ">")
    .replace(/&#(\d+);/g, (_, n) => String.fromCharCode(Number(n)))
    .replace(/[ \t\r\f\v]+/g, " ").replace(/\n\s*\n+/g, "\n").trim();
}

/** Descarga una página (HTML, texto o PDF) y devuelve su texto plano. Es la herramienta "leer_pagina" del agente. */
export async function leerPagina(u: string, permitirLocal = false): Promise<Lectura> {
  const url = urlPermitida(u, permitirLocal);
  if (!url) return { ok: false, texto: "", error: "URL no permitida (solo http/https públicas)" };
  try {
    const r = await fetch(url.toString(), {
      redirect: "follow", signal: AbortSignal.timeout(20000),
      headers: { "user-agent": "Mozilla/5.0 (compatible; LectorPDF/2.0)", "accept-language": "es-EC,es;q=0.9,en;q=0.5", accept: "text/html,application/xhtml+xml,application/pdf,text/plain,*/*;q=0.5" },
    });
    if (!r.ok) return { ok: false, texto: "", error: `HTTP ${r.status}` };
    const tipo = (r.headers.get("content-type") || "").toLowerCase();
    const buf = new Uint8Array(await r.arrayBuffer());
    if (buf.length > MAX_BYTES) return { ok: false, texto: "", error: "Archivo demasiado grande" };
    if (tipo.includes("pdf") || url.pathname.toLowerCase().endsWith(".pdf")) {
      const pags = await textoPorPagina(buf);
      return { ok: true, texto: pags.slice(0, 40).map((p) => p.texto).join("\n\n") };
    }
    if (!/(html|text|json|xml)/.test(tipo)) return { ok: false, texto: "", error: `Tipo no legible: ${tipo || "desconocido"}` };
    const crudo = new TextDecoder("utf-8", { fatal: false, ignoreBOM: false }).decode(buf);
    return { ok: true, texto: tipo.includes("html") ? htmlATexto(crudo) : crudo };
  } catch (e) {
    return { ok: false, texto: "", error: String(e).slice(0, 200) };
  }
}
