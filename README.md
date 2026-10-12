# LECTOR PDF

Convierte PDFs corporativos ecuatorianos (oficios IESS, resoluciones SCVS/SEPS…) en una base de datos de entidades con RUC verificado. Extrae las empresas mencionadas, resuelve su RUC con catastros locales y, si no lo encuentra, un agente lo busca en internet dejando URL y cita textual de cada dato.

## Tres piezas

| Carpeta | Qué es |
|---|---|
| `scripts/` | Pipeline ETL original en Python (pasos 1-9, orquestado por `scripts/process_batch.py`). Ver [RUNBOOK.md](RUNBOOK.md). |
| `agent/` | Agente local (Claude Agent SDK) que corre el pipeline y delega las entidades sin RUC a un investigador web. |
| `cloudflare/` | Versión en Cloudflare: Worker + Workflows + D1 + R2, con el agente investigador (OpenAI Responses + `web_search`), panel web y API para subir lotes. |

## Reglas de veracidad del agente
- Cada dato guardado lleva `fuente_url` y una cita textual.
- El servidor vuelve a descargar la página citada y comprueba que el dato (y el nombre de la empresa) estén ahí.
- Un RUC solo entra al maestro con confianza ALTA: fuente oficial verificada, o dos fuentes independientes verificadas. Lo dudoso queda en revisión manual.

## Puesta en marcha
**Pipeline local**
```bash
pip install -r requirements.txt
export OPENAI_API_KEY=...        # Paso 4 (extracción de entidades)
python scripts/process_batch.py --zip_path data/input/LOTE.zip --master_db data/master/master_entities.sqlite --output_dir data/output
```

**Cloudflare** (requiere `wrangler login`; ver límites del plan gratuito abajo)
```bash
cd cloudflare && npm install
npx wrangler d1 migrations apply lector-pdf-db --remote
npx wrangler secret put OPENAI_API_KEY
npx wrangler secret put API_TOKEN
npx wrangler deploy
```

## Datos y secretos
`data/` (ZIP, PDFs, salidas, maestro y catálogos), los Excel y `cloudflare/migracion/` **no se versionan**: contienen información de empresas. Las claves van como *secrets* de Cloudflare o variables de entorno, nunca en el código.

## Límites a tener en cuenta
- Plan gratuito de Workers: 10 ms de CPU por paso de Workflow; descomprimir ZIP y extraer texto de PDFs necesita el plan de pago (Workers Paid).
- El dígito verificador del RUC es solo informativo: varios RUC reales recientes no lo pasan.
