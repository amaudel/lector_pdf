import { extractText, getDocumentProxy } from "unpdf";

export interface PaginaTexto { pagina: number; estado: "OK" | "SIN_TEXTO"; texto: string }

/** Texto por página (equivale al Paso 2 con PyMuPDF). Una página sin texto se marca SIN_TEXTO (probable escaneo). */
export async function textoPorPagina(pdf: Uint8Array): Promise<PaginaTexto[]> {
  const doc = await getDocumentProxy(new Uint8Array(pdf));
  const { text } = await extractText(doc, { mergePages: false });
  const paginas = Array.isArray(text) ? text : [text];
  return paginas.map((t, i) => {
    const limpio = (t ?? "").trim();
    return { pagina: i + 1, estado: limpio ? "OK" : "SIN_TEXTO", texto: limpio };
  });
}
