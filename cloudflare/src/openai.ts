import type { Env } from "./env";

const base = (env: Env) => (env.OPENAI_BASE_URL || "https://api.openai.com/v1").replace(/\/$/, "");

async function post(env: Env, ruta: string, cuerpo: unknown): Promise<any> {
  if (!env.OPENAI_API_KEY) throw new Error("Falta el secret OPENAI_API_KEY (wrangler secret put OPENAI_API_KEY)");
  const r = await fetch(base(env) + ruta, {
    method: "POST",
    headers: { "content-type": "application/json", authorization: `Bearer ${env.OPENAI_API_KEY}` },
    body: JSON.stringify(cuerpo),
  });
  const texto = await r.text();
  if (!r.ok) throw new Error(`OpenAI ${ruta} ${r.status}: ${texto.slice(0, 400)}`);
  return JSON.parse(texto);
}

/** Chat Completions con respuesta JSON (Paso 4). */
export async function chatJSON(env: Env, model: string, content: unknown): Promise<any> {
  const r = await post(env, "/chat/completions", {
    model, temperature: 0, response_format: { type: "json_object" },
    messages: [{ role: "user", content }],
  });
  return JSON.parse(r.choices[0].message.content);
}

/** Responses API (agente investigador). */
export function responses(env: Env, cuerpo: Record<string, unknown>): Promise<any> {
  return post(env, "/responses", cuerpo);
}
