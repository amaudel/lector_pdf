import { unzipSync } from "fflate";

export interface PdfEnZip { ruta: string; nombre: string; datos: Uint8Array }
export interface ResultadoZip { pdfs: PdfEnZip[]; archivosEncontrados: number; ignorados: number; errores: { archivo: string; error: string }[] }

/** Descomprime solo los PDF. Bloquea Zip Slip (rutas absolutas o con '..'). */
export function extraerPdfs(zip: Uint8Array): ResultadoZip {
  let encontrados = 0, ignorados = 0;
  const errores: { archivo: string; error: string }[] = [];
  const bloqueados = new Set<string>();
  const crudo = unzipSync(zip, {
    filter: (f) => {
      if (f.name.endsWith("/")) return false;
      encontrados++;
      if (!f.name.toLowerCase().endsWith(".pdf")) { ignorados++; return false; }
      const partes = f.name.replace(/\\/g, "/").split("/");
      if (f.name.startsWith("/") || /^[a-zA-Z]:/.test(f.name) || partes.includes("..")) {
        errores.push({ archivo: f.name, error: "Intento de Path Traversal bloqueado (Zip Slip)" });
        bloqueados.add(f.name);
        return false;
      }
      return true;
    },
  });
  const pdfs = Object.entries(crudo).map(([ruta, datos]) => ({
    ruta: ruta.replace(/\\/g, "/"), nombre: ruta.replace(/\\/g, "/").split("/").pop() || ruta, datos,
  }));
  return { pdfs, archivosEncontrados: encontrados, ignorados, errores };
}

export async function sha256(datos: Uint8Array): Promise<string> {
  const h = await crypto.subtle.digest("SHA-256", datos);
  return [...new Uint8Array(h)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export function base64(datos: Uint8Array): string {
  let s = "";
  const trozo = 0x8000;
  for (let i = 0; i < datos.length; i += trozo) s += String.fromCharCode(...datos.subarray(i, i + trozo));
  return btoa(s);
}
