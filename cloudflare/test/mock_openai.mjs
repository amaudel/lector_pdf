// OpenAI simulado para pruebas locales: /chat/completions (extracción) y /responses (agente con guion fijo).
import http from "node:http";
const PORT = 8799;
let n = 0;
const cadenas = new Map(); // respId -> { nombre, paso }
const RE_EMP = /([A-ZÁÉÍÓÚÑ0-9][A-Za-zÁÉÍÓÚÑáéíóúñ0-9&.,' -]{3,80}?\s(?:S\.A\.S\.?|S\.A\.|CIA\.? ?LTDA\.?|C\.A\.))/g;
const rucDe = (s) => { let h = 7; for (const c of s) h = (h * 31 + c.charCodeAt(0)) % 1000000; return "1791" + String(h).padStart(6, "0") + "001"; };

function leer(req) { return new Promise((r) => { let b = ""; req.on("data", (c) => (b += c)); req.on("end", () => r(b)); }); }
const json = (res, o, s = 200) => { res.writeHead(s, { "content-type": "application/json" }); res.end(JSON.stringify(o)); };

http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://127.0.0.1:${PORT}`);
  if (url.pathname === "/pagina") {
    const nombre = url.searchParams.get("n") || "";
    res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
    return res.end(`<html><body><h1>Ficha societaria</h1><p>Razón social: ${nombre}</p><p>RUC ${rucDe(nombre)}</p><p>Estado: ACTIVA</p><script>alert(1)</script></body></html>`);
  }
  const body = JSON.parse((await leer(req)) || "{}");
  if (url.pathname.endsWith("/chat/completions")) {
    const contenido = body.messages[0].content;
    const texto = typeof contenido === "string" ? contenido : contenido.map((c) => c.text || "").join(" ");
    const cuerpo = texto.split('TEXTO EXTRAÍDO (Página de Contexto):')[1] || texto;
    const vistos = new Set(), ents = [];
    for (const m of cuerpo.matchAll(RE_EMP)) {
      const nombre = m[1].trim().replace(/^(de|la|el|empresa|compañía|compania|sociedad)\s+/i, "");
      if (vistos.has(nombre)) continue; vistos.add(nombre);
      const ruc = (cuerpo.match(/\b\d{13}\b/) || [null])[0];
      ents.push({ razon_social_original: nombre, ruc_detectado_en_texto: ruc, provincia_mencionada: /Quito/i.test(cuerpo) ? "Pichincha" : null,
        tipo_entidad_detectada: "EMPRESA", fragmento_evidencia: nombre, nivel_confianza_extraccion: ruc ? "ALTA" : "MEDIA", estado_entidad: "DETECTADA" });
    }
    if (!ents.length) ents.push({ razon_social_original: null, ruc_detectado_en_texto: null, provincia_mencionada: null, tipo_entidad_detectada: null, fragmento_evidencia: null, nivel_confianza_extraccion: null, estado_entidad: "SIN_ENTIDAD_CLARA" });
    return json(res, { choices: [{ message: { content: JSON.stringify({ entidades: ents }) } }] });
  }
  if (url.pathname.endsWith("/responses")) {
    let cadena = cadenas.get(body.previous_response_id);
    if (!cadena) {
      const ent = JSON.parse(body.input[0].content.split("\n").slice(1).join("\n").split("\n\nCampos")[0]);
      cadena = { nombre: ent.razon_social, clave: ent.clave, paso: 0 };
    }
    const id = `resp_${++n}`;
    const llamada = (name, args) => ({ type: "function_call", call_id: `call_${n}_${name}`, name, arguments: JSON.stringify(args) });
    const pagina = `http://127.0.0.1:${PORT}/pagina?n=${encodeURIComponent(cadena.nombre)}`;
    const guion = [
      () => [{ type: "web_search_call", id: "ws_1", status: "completed" }, llamada("registrar_intento", { estrategia: "búsqueda web exacta", consulta: `"${cadena.nombre}" RUC Ecuador`, resultado: "ficha societaria encontrada" }),
             llamada("leer_pagina", { url: pagina })],
      () => [llamada("registrar_hallazgo", { campo: "ruc", valor: rucDe(cadena.nombre), fuente_url: pagina, evidencia: `${cadena.nombre} RUC ${rucDe(cadena.nombre)}`, confianza: "ALTA" }),
             llamada("registrar_hallazgo", { campo: "estado_legal", valor: "ACTIVA", fuente_url: pagina, evidencia: "Estado: ACTIVA", confianza: "ALTA" }),
             llamada("registrar_hallazgo", { campo: "ruc", valor: "1791111111001", fuente_url: pagina, evidencia: "no contiene el numero", confianza: "ALTA" }),
             llamada("registrar_hallazgo", { campo: "ruc", valor: rucDe(cadena.nombre), fuente_url: pagina.replace("127.0.0.1", "localhost"), evidencia: `${cadena.nombre} RUC ${rucDe(cadena.nombre)}`, confianza: "ALTA" })],
      () => [llamada("cerrar_entidad", { estado: "ENCONTRADO", notas: "mock" })],
      () => [{ type: "message", content: [{ type: "output_text", text: "Entidad cerrada." }] }],
    ];
    const salida = guion[Math.min(cadena.paso, guion.length - 1)]();
    cadenas.set(id, { ...cadena, paso: cadena.paso + 1 });
    return json(res, { id, output: salida });
  }
  json(res, { error: "ruta no simulada" }, 404);
}).listen(PORT, () => console.log("mock openai en", PORT));
