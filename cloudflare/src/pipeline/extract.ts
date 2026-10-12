import type { Env } from "../env";
import { chatJSON } from "../openai";

export interface EntidadLLM {
  razon_social_original: string | null; ruc_detectado_en_texto: string | null; provincia_mencionada: string | null;
  tipo_entidad_detectada: string | null; fragmento_evidencia: string | null;
  nivel_confianza_extraccion: string | null; estado_entidad: string | null;
}

// Mismo prompt del Paso 4 (4_extract_entities.py).
const PROMPT = (texto: string) => `
Eres un extractor de datos conservador y estricto especializado en documentos legales/administrativos de Ecuador.
Tu única tarea es leer el siguiente TEXTO EXTRAÍDO de una página PDF e identificar menciones explícitas a entidades empresariales, compañías, cooperativas, instituciones públicas o personas naturales con negocio.

REGLAS ESTRICTAS DE EXTRACCIÓN ("CERO ALUCINACIÓN"):
1. NO inventes ni infieras datos que no estén escritos literalmente en el texto.
2. Si aparece un RUC (generalmente 13 dígitos numéricos terminados en 001) extráelo SOLO si está explícitamente contenido en el texto. Si no hay, pon null.
3. Si un RUC parece pertenecer a otra entidad (cruces), trata de no mezclarlo.
4. "razon_social_original" debe ser el texto tal cual aparece. No corrijas faltas ortográficas.
5. "provincia_mencionada" extráela solo si el texto dice la provincia explícitamente asociada a la dirección o ciudad de la empresa.
6. "fragmento_evidencia" debe ser una pequeña cita exacta del texto original (aprox 10-15 palabras) con la que justificas la extracción.
7. "nivel_confianza_extraccion":
   - ALTA: Tienes Razón Social + RUC claros.
   - MEDIA: Razón Social muy clara, pero sin RUC.
   - BAJA: Mención ambigua, incompleta o parece ser un individuo sin rol empresarial claro.
8. "estado_entidad":
   - DETECTADA: Para confianzas ALTA o MEDIA.
   - DUDOSA: Para confianza BAJA.
   - Si no hay absolutamente ninguna entidad, devuelve un solo objeto en la lista con estado_entidad="SIN_ENTIDAD_CLARA" y los demás campos null.
9. IGNORA Y OMITE OBLIGATORIAMENTE las menciones al "Instituto Ecuatoriano de Seguridad Social" (IESS) y al "Servicio de Rentas Internas" (SRI). JAMAS los extraigas como entidades empresariales.
10. IGNORA Y OMITE OBLIGATORIAMENTE a las entidades, personas o cargos que figuren únicamente como remitentes o destinatarios en las cabeceras de memorandos u oficios (usualmente indicados en campos como DE:, PARA:, De:, Para:, A:, Remitente:, Destinatario:). Concéntrate únicamente en extraer las entidades que sean el sujeto u objeto de las resoluciones o cuerpo de texto del documento.

FORMATO DE SALIDA (ESTRICTAMENTE JSON con la clave 'entidades'):
{
  "entidades": [
    {
      "razon_social_original": "string o null",
      "ruc_detectado_en_texto": "string o null",
      "provincia_mencionada": "string o null",
      "tipo_entidad_detectada": "string (EMPRESA, COOPERATIVA, AUTORIDAD, COMERCIO, etc) o null",
      "fragmento_evidencia": "string o null",
      "nivel_confianza_extraccion": "ALTA | MEDIA | BAJA",
      "estado_entidad": "DETECTADA | DUDOSA | SIN_ENTIDAD_CLARA"
    }
  ]
}

TEXTO EXTRAÍDO (Página de Contexto):
"""${texto}"""
`;

function normalizarLista(r: any): EntidadLLM[] {
  const l = r?.entidades;
  if (Array.isArray(l)) return l;
  return l ? [l] : [];
}

/** Página con texto. */
export async function extraerDeTexto(env: Env, texto: string): Promise<EntidadLLM[]> {
  return normalizarLista(await chatJSON(env, env.MODELO_EXTRACCION, PROMPT(texto)));
}

/** Página escaneada: se envía el PDF completo y se pide analizar solo la página indicada (OpenAI lo rasteriza). */
export async function extraerDePaginaEscaneada(env: Env, pdfBase64: string, nombre: string, pagina: number): Promise<EntidadLLM[]> {
  const instruccion = PROMPT(`[Página escaneada. Analiza visualmente SOLO la página ${pagina} del PDF adjunto e ignora las demás páginas.]`);
  return normalizarLista(await chatJSON(env, env.MODELO_EXTRACCION, [
    { type: "text", text: instruccion },
    { type: "file", file: { filename: nombre, file_data: `data:application/pdf;base64,${pdfBase64}` } },
  ]));
}
