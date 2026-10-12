"""Herramientas (MCP en proceso) que el agente usa sobre el pipeline y la base de datos."""
import asyncio
import json
import os
import sys

from claude_agent_sdk import create_sdk_mcp_server, tool

import store
from ruc import validar_ruc


def _ok(data):
    texto = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=1, default=str)
    return {"content": [{"type": "text", "text": texto}]}


def _err(msg):
    return {"content": [{"type": "text", "text": f"ERROR: {msg}"}], "is_error": True}


@tool("listar_zips_pendientes", "Lista los ZIP de data/input que aún no se integraron al maestro (no están en processed_batches).", {})
async def listar_zips_pendientes(args):
    return _ok({"zips_pendientes": store.zips_sin_procesar()})


@tool("procesar_zip",
      "Corre el pipeline ETL completo (pasos 1-9) sobre un ZIP de data/input: descomprime, extrae texto, "
      "detecta entidades con OpenAI, las resuelve contra catastros locales y carga al maestro las que tienen RUC. "
      "Puede tardar varios minutos. Después de esto, usa listar_pendientes para ver qué quedó sin RUC.",
      {"zip": str, "dry_run": bool})
async def procesar_zip(args):
    nombre = args["zip"]
    ruta = (store.INPUT / nombre).resolve()
    if ruta.parent != store.INPUT.resolve() or not ruta.exists():
        return _err(f"'{nombre}' no existe en data/input")
    if not os.environ.get("OPENAI_API_KEY") and not args.get("dry_run"):
        return _err("falta OPENAI_API_KEY (el Paso 4 usa OpenAI). Configúrala y reintenta.")
    cmd = [sys.executable, "scripts/process_batch.py", "--zip_path", str(ruta),
           "--master_db", str(store.MASTER), "--output_dir", str(store.OUTPUT)]
    if args.get("dry_run"):
        cmd.append("--dry_run")
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=str(store.BASE), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    try:
        salida, _ = await asyncio.wait_for(proc.communicate(), timeout=3600)
    except asyncio.TimeoutError:
        proc.kill()
        return _err("el pipeline excedió 1 hora y fue cancelado")
    cola = "\n".join(salida.decode("utf-8", "replace").splitlines()[-25:])
    reporte = store.OUTPUT / f"pipeline_run_report_{store.lote_de(nombre)}.json"
    pasos = json.loads(reporte.read_text(encoding="utf-8")).get("estado_final_pasos") if reporte.exists() else None
    return _ok({"exit_code": proc.returncode, "estado_pasos": pasos, "ultimas_lineas": cola})


@tool("listar_pendientes",
      "Lista entidades que el agente debe investigar en internet. modo='ruc': entidades sin RUC (agrupadas por nombre en todos "
      "los lotes, con la cita del PDF donde aparecen). modo='campos': entidades del maestro a las que faltan campos por completar.",
      {"modo": str, "lote": str, "limite": int, "campos": list})
async def listar_pendientes(args):
    modo, limite = args.get("modo", "ruc"), int(args.get("limite") or 10)
    if modo == "campos":
        return _ok({"entidades": store.pendientes_campos(args.get("campos") or store.CAMPOS_DEFAULT, limite)})
    lista, resumen = store.pendientes_ruc(args.get("lote") or None, limite)
    return _ok({"resumen": resumen, "entidades": lista})


@tool("contexto_pdf", "Devuelve el texto de una página de un PDF ya procesado, para entender de qué trata el documento "
      "(p. ej. si la empresa está en liquidación, qué ciudad, qué institución la menciona).",
      {"lote": str, "archivo": str, "pagina": int})
async def contexto_pdf(args):
    texto = store.contexto_pdf(args["lote"], args["archivo"], args["pagina"])
    return _ok(texto) if texto else _err("no se encontró esa página en el consolidado del lote")


@tool("buscar_catalogo_local",
      "Busca en los catastros locales descargados (SRI, SEPS) por razón social o por RUC. Rápido y gratis: úsalo ANTES de ir a internet. "
      "Un resultado solo sirve si el nombre coincide de forma inequívoca.",
      {"consulta": str})
async def buscar_catalogo_local(args):
    return _ok(store.buscar_catalogo(args["consulta"]))


@tool("validar_ruc", "Chequeo estructural de un RUC ecuatoriano (13 dígitos, provincia, dígito verificador). "
      "Informativo: muchos RUC reales recientes fallan el verificador, así que un fallo no lo descarta.", {"ruc": str})
async def validar_ruc_tool(args):
    return _ok(validar_ruc(args["ruc"]))


@tool("registrar_intento", "Deja constancia en la bitácora de cada estrategia de búsqueda probada (aunque no haya dado resultado).",
      {"clave": str, "estrategia": str, "consulta": str, "resultado": str})
async def registrar_intento(args):
    n = store.registrar_intento(args["clave"], args["estrategia"], args["consulta"], args["resultado"])
    return _ok({"intentos_acumulados": n})


@tool("registrar_hallazgo",
      "Guarda un dato encontrado en internet. Exige fuente_url (la URL real) y evidencia (cita textual copiada de la página). "
      "Para campo='ruc' la evidencia debe contener el RUC. confianza: ALTA solo si la fuente es oficial (SRI, Supercias/SCVS, SEPS, "
      "Registro Mercantil, SERCOP) o dos fuentes independientes coinciden en nombre+RUC; MEDIA si una sola fuente no oficial; BAJA si es dudoso. "
      "Si buscaste un campo y no existe públicamente, regístralo con valor='NO_DISPONIBLE'.",
      {"clave": str, "campo": str, "valor": str, "fuente_url": str, "evidencia": str, "confianza": str})
async def registrar_hallazgo(args):
    r = store.registrar_hallazgo(args["clave"], args["campo"], args["valor"], args.get("fuente_url"),
                                args.get("evidencia"), args["confianza"])
    return _ok(r) if r.get("ok") else _err(r["error"])


@tool("cerrar_entidad",
      "Cierra la investigación de una entidad. estado='ENCONTRADO' (requiere un hallazgo ruc con confianza ALTA; la promueve al maestro), "
      "'NO_ENCONTRADO' (solo tras agotar las estrategias; describe en notas qué probaste) o 'REVISION_MANUAL' (hay candidatos pero no puedes decidir).",
      {"clave": str, "estado": str, "notas": str})
async def cerrar_entidad(args):
    r = store.cerrar_entidad(args["clave"], args["estado"], args.get("notas", ""))
    return _ok(r) if r.get("ok") else _err(r["error"])


TODAS = [listar_zips_pendientes, procesar_zip, listar_pendientes, contexto_pdf, buscar_catalogo_local,
         validar_ruc_tool, registrar_intento, registrar_hallazgo, cerrar_entidad]
# Las que puede usar el subagente investigador (nunca procesar ZIP)
DEL_INVESTIGADOR = ["contexto_pdf", "buscar_catalogo_local", "validar_ruc", "registrar_intento",
                    "registrar_hallazgo", "cerrar_entidad"]

servidor = create_sdk_mcp_server("lector", "1.0.0", TODAS)
