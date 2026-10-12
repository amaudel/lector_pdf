import os
import sys
import json
import sqlite3
import asyncio
import threading
import subprocess
import shutil
import uvicorn
from pathlib import Path
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel
from fastapi import FastAPI, Request, File, UploadFile, HTTPException, Query
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

# ── Rutas de Trabajo ──────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "data" / "input"
OUTPUT_DIR = BASE_DIR / "data" / "output"
EXCEL_DIR = OUTPUT_DIR / "REPORTES DE EXCEL"
MASTER_DB = BASE_DIR / "data" / "master" / "master_entities.sqlite"

# Asegurar directorios mínimos
INPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
EXCEL_DIR.mkdir(parents=True, exist_ok=True)

# ── Pasos y Parsing de Salida ─────────────────────────────────────────
PASOS_DETECTADOS = [
    ("Preparando Paso 1", 10),
    ("Preparando Paso 2", 15),
    ("Preparando Paso 3", 10),
    ("Preparando Paso 4", 25),
    ("Preparando Paso 5", 10),
    ("Preparando Paso 7 ", 10),
    ("Preparando Paso 7.5", 5),
    ("Preparando Paso 8", 5),
    ("Preparando Paso 9", 10),
]
TOTAL_PESO = sum(p for _, p in PASOS_DETECTADOS)

PATRON_ERROR_REAL = [
    "Traceback (most recent call last)",
    "Error cargando",
    "FileNotFoundError",
    "ModuleNotFoundError",
    "KeyError:",
    "AttributeError:",
    "SyntaxError:",
    "JSONDecodeError",
    "PermissionError",
    "[X]",
    "FAILED",
    "sys.exit(1)",
]

PATRON_IGNORAR = [
    "Errores de extracción",
    "Errores de API",
    "Docs con Error",
    "Páginas con ERROR",
    "Páginas con ERROR",
    "Errores Detectados: 0",
    "Error    : 0",
]

# ── Estado Global del Servidor ────────────────────────────────────────
is_running = False
current_process = None
progress_state = {
    "lote": "",
    "lote_index": 0,
    "lote_total": 0,
    "paso": "Esperando archivos...",
    "pct_lote": 0,
    "pct_global": 0,
    "failed_batch": "Ninguno"
}
listeners = []
main_loop = None

# ── Inicialización de FastAPI ──────────────────────────────────────────
app = FastAPI(title="LECTOR PDF API", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    global main_loop
    main_loop = asyncio.get_running_loop()

class RunConfig(BaseModel):
    enable_web_enrichment: bool = False
    force_reprocess: bool = False

# ── Utilidades de Envío de Eventos (Thread-safe) ──────────────────────
def broadcast(event_type: str, data: dict):
    if not main_loop:
        return
    async def push():
        for q in list(listeners):
            await q.put({"event": event_type, "data": data})
    asyncio.run_coroutine_threadsafe(push(), main_loop)

# ── Función Principal de Procesamiento ─────────────────────────────────
def run_pipeline_thread(enable_web_enrichment: bool, force_reprocess: bool):
    global is_running, current_process, progress_state
    is_running = True
    broadcast("status", {"is_running": True, "progress": progress_state})

    try:
        # 1. PDFs sueltos
        pdfs = list(INPUT_DIR.glob("*.pdf"))
        if pdfs:
            broadcast("log", {"line": f"[INFO] Se encontraron {len(pdfs)} PDF(s) sueltos. Empaquetando...", "type": "warn"})
            cmd_zip = [sys.executable, "-u", str(BASE_DIR / "scripts" / "crear_zip_desde_pdfs.py"), str(INPUT_DIR)]
            p_zip = subprocess.Popen(cmd_zip, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=str(BASE_DIR), text=True, encoding="utf-8", errors="replace")
            for line in p_zip.stdout:
                broadcast("log", {"line": line.rstrip(), "type": "info"})
            p_zip.wait()

        # 2. Obtener los ZIPs a procesar
        zips = sorted(INPUT_DIR.glob("*.zip"))
        if not zips:
            broadcast("log", {"line": "❌ No se encontraron archivos ZIP ni PDFs sueltos en data/input.", "type": "error"})
            broadcast("done", {"success": False, "message": "No hay archivos para procesar."})
            is_running = False
            broadcast("status", {"is_running": False, "progress": progress_state})
            return

        total_zips = len(zips)
        progress_state = {
            "lote": "",
            "lote_index": 0,
            "lote_total": total_zips,
            "paso": "Iniciando...",
            "pct_lote": 0,
            "pct_global": 0,
            "failed_batch": "Ninguno"
        }
        broadcast("progress", progress_state)

        errores = []

        for idx, zip_path in enumerate(zips):
            # Si se canceló el proceso
            if not is_running:
                break

            nombre = zip_path.name
            progress_state["lote"] = nombre
            progress_state["lote_index"] = idx + 1
            progress_state["paso"] = "Descomprimiendo lote..."
            progress_state["pct_lote"] = 0
            progress_state["pct_global"] = int((idx / total_zips) * 100)
            
            broadcast("progress", progress_state)
            broadcast("log", {"line": f"\n━━━ Lote {idx+1}/{total_zips}: {nombre} ━━━", "type": "info"})

            # Configurar comando
            cmd = [
                sys.executable, "-u", "scripts/process_batch.py",
                "--zip_path", str(zip_path),
                "--master_db", str(MASTER_DB),
                "--output_dir", str(OUTPUT_DIR)
            ]
            if enable_web_enrichment:
                cmd.append("--enable_web_enrichment")
            if force_reprocess:
                cmd.append("--force_reprocess_master")

            paso_actual_peso = 0
            error_detectado = False
            lineas_error = []
            proceso_exitoso = False

            current_process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                cwd=str(BASE_DIR), text=True, encoding="utf-8", errors="replace",
                bufsize=1
            )

            for line in current_process.stdout:
                linea = line.rstrip()
                if not linea:
                    continue

                # Detectar éxito
                if "Errores Detectados: 0" in linea:
                    proceso_exitoso = True

                # Identificar Paso
                paso_nombre = None
                for fragmento, peso in PASOS_DETECTADOS:
                    if fragmento in linea:
                        paso_nombre = fragmento.replace("Preparando ", "").strip()
                        paso_actual_peso += peso
                        break

                # Identificar errores reales
                es_ignorar = any(p in linea for p in PATRON_IGNORAR)
                es_error_real = (not es_ignorar and any(p in linea for p in PATRON_ERROR_REAL))
                if es_error_real:
                    lineas_error.append(linea)
                    error_detectado = True

                # Calcular porcentajes
                pct_lote = min(int(paso_actual_peso / TOTAL_PESO * 100), 99)
                pct_global = int(((idx + pct_lote / 100) / total_zips) * 100)

                progress_state["pct_lote"] = pct_lote
                progress_state["pct_global"] = pct_global
                if paso_nombre:
                    progress_state["paso"] = paso_nombre

                broadcast("progress", progress_state)

                # Clasificar tipo de log
                tag = "info"
                if es_error_real:
                    tag = "error"
                elif any(k in linea for k in ["[OK]", "OK :", ": OK", "exitosa", "éxito", "\u00e9xito"]):
                    tag = "ok"
                elif "OMITIDO" in linea:
                    tag = "dim"

                broadcast("log", {"line": linea, "type": tag})

            current_process.wait()
            rc = current_process.returncode

            # Validar fallo real
            fallo_real = (rc != 0) or (error_detectado and not proceso_exitoso)
            if fallo_real:
                msg_error = "\n".join(lineas_error[-8:]) or f"Código de salida: {rc}"
                errores.append(nombre)
                broadcast("log", {"line": f"❌ Lote fallido: '{nombre}'\nDetalle: {msg_error}", "type": "error"})
                progress_state["paso"] = "Error detectado"
                progress_state["failed_batch"] = ", ".join(errores)
                broadcast("progress", progress_state)
            else:
                broadcast("log", {"line": f"✅ Lote '{nombre}' completado con éxito.", "type": "ok"})
                progress_state["pct_lote"] = 100
                progress_state["pct_global"] = int(((idx + 1) / total_zips) * 100)
                progress_state["paso"] = "Lote completado"
                broadcast("progress", progress_state)

        # Limpiar ZIP temporal
        tmp = INPUT_DIR / "pdfs_sueltos.zip"
        if tmp.exists():
            tmp.unlink()

        is_running = False
        broadcast("status", {"is_running": False, "progress": progress_state})
        broadcast("done", {"success": len(errores) == 0, "errors": errores})

    except Exception as e:
        broadcast("log", {"line": f"❌ Error crítico en el pipeline: {str(e)}", "type": "error"})
        is_running = False
        broadcast("status", {"is_running": False, "progress": progress_state})
        broadcast("done", {"success": False, "message": str(e)})

# ── Endpoints REST API ────────────────────────────────────────────────

@app.get("/")
def read_root():
    index_path = BASE_DIR / "static" / "index.html"
    if index_path.exists():
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Servidor LECTOR PDF Activo</h1><p>No se encontró el archivo 'static/index.html'.</p>")

@app.get("/api/status")
def get_status():
    stats = {"total_entities": 0, "total_batches": 0, "total_evidence": 0}
    if MASTER_DB.exists():
        try:
            conn = sqlite3.connect(MASTER_DB)
            c = conn.cursor()
            
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='master_entities'")
            if c.fetchone():
                c.execute("SELECT COUNT(*) FROM master_entities")
                stats["total_entities"] = c.fetchone()[0]

            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='processed_batches'")
            if c.fetchone():
                c.execute("SELECT COUNT(*) FROM processed_batches")
                stats["total_batches"] = c.fetchone()[0]

            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='master_evidence'")
            if c.fetchone():
                c.execute("SELECT COUNT(*) FROM master_evidence")
                stats["total_evidence"] = c.fetchone()[0]
                
            conn.close()
        except Exception as e:
            print(f"Error cargando estadísticas de base de datos: {e}")

    # Contar archivos pendientes
    pending_zips = len(list(INPUT_DIR.glob("*.zip")))
    pending_pdfs = len(list(INPUT_DIR.glob("*.pdf")))

    return {
        "is_running": is_running,
        "progress": progress_state,
        "stats": stats,
        "pending_zips": pending_zips,
        "pending_pdfs": pending_pdfs
    }

@app.get("/api/files")
def get_files():
    # Listar inputs
    input_files = []
    for f in sorted(INPUT_DIR.iterdir()):
        if f.name == ".keep" or f.is_dir():
            continue
        input_files.append({
            "name": f.name,
            "size": f.stat().st_size,
            "mtime": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
            "type": "input"
        })

    # Listar outputs (Excel en REPORTES DE EXCEL)
    output_files = []
    if EXCEL_DIR.exists():
        for f in sorted(EXCEL_DIR.glob("*.xlsx")):
            output_files.append({
                "name": f.name,
                "size": f.stat().st_size,
                "mtime": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                "type": "output"
            })

    return {"inputs": input_files, "outputs": output_files}

@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    ext = Path(file.filename).suffix.lower()
    if ext not in [".zip", ".pdf"]:
        raise HTTPException(status_code=400, detail="Solo se permiten archivos .zip y .pdf")
    
    target_path = INPUT_DIR / file.filename
    with open(target_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    return {"filename": file.filename, "size": target_path.stat().st_size}

@app.delete("/api/files/{file_type}/{filename}")
def delete_file(file_type: str, filename: str):
    if file_type == "input":
        target = INPUT_DIR / filename
    elif file_type == "output":
        target = EXCEL_DIR / filename
    else:
        raise HTTPException(status_code=400, detail="Tipo de archivo inválido")

    if not target.exists() or target.is_dir():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")

    try:
        target.unlink()
        return {"status": "deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"No se pudo eliminar: {str(e)}")

@app.get("/api/download/output/{filename}")
def download_output(filename: str):
    target = EXCEL_DIR / filename
    if not target.exists() or target.is_dir():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return FileResponse(path=target, filename=filename, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

@app.get("/api/database")
def query_database(
    q: Optional[str] = None,
    provincia: Optional[str] = None,
    tipo: Optional[str] = None,
    fuente: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    sort_by: str = "razon_social_canonica",
    sort_order: str = "asc"
):
    if not MASTER_DB.exists():
        return {"total": 0, "page": page, "page_size": page_size, "data": []}

    try:
        conn = sqlite3.connect(MASTER_DB)
        c = conn.cursor()
        
        # Verificar si la tabla existe
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='master_entities'")
        if not c.fetchone():
            conn.close()
            return {"total": 0, "page": page, "page_size": page_size, "data": []}

        # Construir consulta
        where_clauses = ["1=1"]
        params = []

        if q:
            where_clauses.append("(ruc LIKE ? OR razon_social_canonica LIKE ? OR razon_social_normalizada LIKE ?)")
            q_param = f"%{q}%"
            params.extend([q_param, q_param, q_param])

        if provincia:
            where_clauses.append("provincia_preferida = ?")
            params.append(provincia)

        if tipo:
            where_clauses.append("tipo_entidad = ?")
            params.append(tipo)

        if fuente:
            where_clauses.append("fuente_primaria = ?")
            params.append(fuente)

        where_str = " AND ".join(where_clauses)

        # Contar total
        c.execute(f"SELECT COUNT(*) FROM master_entities WHERE {where_str}", params)
        total = c.fetchone()[0]

        # Validar ordenamiento
        allowed_sorts = ["ruc", "razon_social_canonica", "tipo_entidad", "provincia_preferida", "fuente_primaria", "total_menciones", "fecha_ultima_actualizacion"]
        if sort_by not in allowed_sorts:
            sort_by = "razon_social_canonica"
        if sort_order.lower() not in ["asc", "desc"]:
            sort_order = "asc"

        # Paginación
        limit = page_size
        offset = (page - 1) * page_size
        
        query_str = f"""
            SELECT ruc, razon_social_canonica, razon_social_normalizada, tipo_entidad,
                   provincia_preferida, estado_resolucion_master, fuente_primaria,
                   fecha_primera_aparicion, fecha_ultima_actualizacion, total_lotes_detectado,
                   total_menciones
            FROM master_entities
            WHERE {where_str}
            ORDER BY {sort_by} {sort_order}
            LIMIT ? OFFSET ?
        """
        c.execute(query_str, params + [limit, offset])
        rows = c.fetchall()

        columns = [
            "ruc", "razon_social_canonica", "razon_social_normalizada", "tipo_entidad",
            "provincia_preferida", "estado_resolucion_master", "fuente_primaria",
            "fecha_primera_aparicion", "fecha_ultima_actualizacion", "total_lotes_detectado",
            "total_menciones"
        ]
        
        data = [dict(zip(columns, row)) for row in rows]
        conn.close()
        
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "data": data
        }
    except Exception as e:
        print(f"Error consultando DB: {e}")
        return {"total": 0, "page": page, "page_size": page_size, "data": [], "error": str(e)}

@app.get("/api/filters")
def get_database_filters():
    if not MASTER_DB.exists():
        return {"provincias": [], "tipos": [], "fuentes": []}

    try:
        conn = sqlite3.connect(MASTER_DB)
        c = conn.cursor()
        
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='master_entities'")
        if not c.fetchone():
            conn.close()
            return {"provincias": [], "tipos": [], "fuentes": []}

        c.execute("SELECT DISTINCT provincia_preferida FROM master_entities WHERE provincia_preferida IS NOT NULL AND provincia_preferida != ''")
        provincias = [row[0] for row in c.fetchall()]

        c.execute("SELECT DISTINCT tipo_entidad FROM master_entities WHERE tipo_entidad IS NOT NULL AND tipo_entidad != ''")
        tipos = [row[0] for row in c.fetchall()]

        c.execute("SELECT DISTINCT fuente_primaria FROM master_entities WHERE fuente_primaria IS NOT NULL AND fuente_primaria != ''")
        fuentes = [row[0] for row in c.fetchall()]

        conn.close()
        return {
            "provincias": sorted(provincias),
            "tipos": sorted(tipos),
            "fuentes": sorted(fuentes)
        }
    except Exception as e:
        print(f"Error cargando filtros: {e}")
        return {"provincias": [], "tipos": [], "fuentes": []}

@app.get("/api/evidence/{ruc}")
def get_evidence(ruc: str):
    if not MASTER_DB.exists():
        return []

    try:
        conn = sqlite3.connect(MASTER_DB)
        c = conn.cursor()
        
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='master_evidence'")
        if not c.fetchone():
            conn.close()
            return []

        c.execute("""
            SELECT id, lote, archivo_origen, pagina_pdf, fragmento_evidencia,
                   estado_resolucion_origen, fecha_ingesta, fuente_ruc
            FROM master_evidence
            WHERE ruc = ?
            ORDER BY fecha_ingesta DESC
        """, (ruc,))
        rows = c.fetchall()
        
        columns = ["id", "lote", "archivo_origen", "pagina_pdf", "fragmento_evidencia", "estado_resolucion_origen", "fecha_ingesta", "fuente_ruc"]
        evidence = [dict(zip(columns, row)) for row in rows]
        conn.close()
        return evidence
    except Exception as e:
        print(f"Error cargando evidencias de {ruc}: {e}")
        return []

@app.post("/api/start")
def start_pipeline(config: RunConfig):
    global is_running
    if is_running:
        raise HTTPException(status_code=400, detail="El procesamiento ya está en curso.")

    # Iniciar pipeline en segundo plano
    t = threading.Thread(
        target=run_pipeline_thread,
        args=(config.enable_web_enrichment, config.force_reprocess),
        daemon=True
    )
    t.start()
    return {"status": "started"}

@app.post("/api/stop")
def stop_pipeline():
    global is_running, current_process
    if not is_running:
        return {"status": "not_running"}

    is_running = False
    if current_process:
        try:
            current_process.terminate()
            broadcast("log", {"line": "🛑 Procesamiento cancelado por el usuario.", "type": "warn"})
        except Exception as e:
            print(f"Error cancelando proceso: {e}")

    return {"status": "stopping"}

@app.get("/api/stream")
async def stream_logs(request: Request):
    q = asyncio.Queue()
    listeners.append(q)

    async def event_generator():
        try:
            # Enviar estado inicial
            yield f"data: {json.dumps({'event': 'status', 'data': {'is_running': is_running, 'progress': progress_state}})}\n\n"
            
            while True:
                # Verificar desconexión
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=1.0)
                    yield f"data: {json.dumps(msg)}\n\n"
                except asyncio.TimeoutError:
                    # Enviar ping de mantenimiento de conexión
                    yield ": ping\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            listeners.remove(q)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

# ── Ejecución del Servidor ───────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run("web_server:app", host="127.0.0.1", port=8000, reload=False)
