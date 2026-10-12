"""
Monitor Visual de Procesamiento - LECTOR PDF
Interfaz gráfica premium con diseño de dos columnas, panel de estadísticas y barra de progreso.
Delega el procesamiento a process_batch.py (el orquestador oficial).
"""
import sys
import threading
import subprocess
import sqlite3
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from pathlib import Path
from datetime import datetime

# ── Rutas ────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).resolve().parent
INPUT_DIR  = BASE_DIR / "data" / "input"
OUTPUT_DIR = BASE_DIR / "data" / "output"
MASTER_DB  = BASE_DIR / "data" / "master" / "master_entities.sqlite"

# ── Pasos que reconocemos en la salida de process_batch.py ───────────
PASOS_DETECTADOS = [
    ("Preparando Paso 1", 10),
    ("Preparando Paso 2", 15),
    ("Preparando Paso 3", 10),
    ("Preparando Paso 4", 25),
    ("Preparando Paso 5", 10),
    ("Preparando Paso 7 ",  10),
    ("Preparando Paso 7.5", 5),
    ("Preparando Paso 8",   5),
    ("Preparando Paso 9",  10),
]
TOTAL_PESO = sum(p for _, p in PASOS_DETECTADOS)

# ── Paleta de colores Premium ────────────────────────────────────────
C = {
    "bg":          "#0b0f19",
    "panel":       "#171e2e",
    "border":      "#2d3748",
    "acento":      "#6366f1",
    "acento_hover":"#4f46e5",
    "ok":          "#10b981",
    "warn":        "#f59e0b",
    "error":       "#ef4444",
    "text":        "#f3f4f6",
    "subtext":     "#9ca3af",
    "barra_bg":    "#1e293b",
}

class MonitorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("LECTOR PDF — Dashboard de Control")
        self.geometry("980x680")
        self.resizable(False, False)
        self.configure(bg=C["bg"])
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        
        self._running = False
        self._errores = []
        
        self._build_ui()
        self._update_db_stats()

    # ── Construcción de la UI ────────────────────────────────────────
    def _build_ui(self):
        # Cabecera superior
        hdr = tk.Frame(self, bg=C["acento"], height=52)
        hdr.pack(fill="x")
        tk.Label(
            hdr, text="⚡  LECTOR PDF  —  Dashboard de Procesamiento",
            bg=C["acento"], fg="white",
            font=("Segoe UI", 12, "bold")
        ).pack(side="left", padx=20, pady=12)

        # Contenedor del Cuerpo Principal
        body = tk.Frame(self, bg=C["bg"], padx=20, pady=20)
        body.pack(fill="both", expand=True)

        # ── COLUMNA IZQUIERDA (Controles y Stats) ────────────────────
        left_col = tk.Frame(body, bg=C["bg"], width=300)
        left_col.pack(side="left", fill="y", padx=(0, 20))
        left_col.pack_propagate(False)

        # Panel de Opciones (Settings)
        opt_panel = tk.LabelFrame(
            left_col, text=" CONFIGURACIÓN ", bg=C["panel"], fg=C["text"],
            bd=1, relief="solid", highlightbackground=C["border"],
            font=("Segoe UI", 9, "bold"), padx=12, pady=12
        )
        opt_panel.pack(fill="x", pady=(0, 15))

        self.var_web = tk.BooleanVar(value=False)
        self.var_force = tk.BooleanVar(value=False)

        cb_web = tk.Checkbutton(
            opt_panel, text="Búsqueda Web (7B / 7.5B)", 
            variable=self.var_web, bg=C["panel"], fg=C["text"], 
            selectcolor=C["bg"], activebackground=C["panel"], 
            activeforeground=C["text"], font=("Segoe UI", 9),
            cursor="hand2"
        )
        cb_web.pack(anchor="w", pady=(0, 8))

        cb_force = tk.Checkbutton(
            opt_panel, text="Forzar Reproceso (Paso 8)", 
            variable=self.var_force, bg=C["panel"], fg=C["text"], 
            selectcolor=C["bg"], activebackground=C["panel"], 
            activeforeground=C["text"], font=("Segoe UI", 9),
            cursor="hand2"
        )
        cb_force.pack(anchor="w")

        # Panel de Estadísticas (Master DB Status)
        stats_panel = tk.LabelFrame(
            left_col, text=" BASE DE DATOS MAESTRA ", bg=C["panel"], fg=C["text"],
            bd=1, relief="solid", highlightbackground=C["border"],
            font=("Segoe UI", 9, "bold"), padx=12, pady=12
        )
        stats_panel.pack(fill="x", pady=(0, 15))

        self.lbl_stat_entities = self._create_stat_row(stats_panel, "Empresas en base:", "0")
        self.lbl_stat_batches = self._create_stat_row(stats_panel, "Lotes procesados:", "0")
        self.lbl_stat_evidence = self._create_stat_row(stats_panel, "Evidencias en PDF:", "0")
        self.lbl_stat_failed = self._create_stat_row(stats_panel, "Lote con error:", "Ninguno")

        # Botón de Acción Principal (Bottom Left)
        self.btn = tk.Button(
            left_col, text="▶  INICIAR PIPELINE",
            bg=C["acento"], fg="white",
            font=("Segoe UI", 11, "bold"),
            relief="flat", bd=0, cursor="hand2",
            activebackground=C["acento_hover"], activeforeground="white",
            command=self._start
        )
        self.btn.pack(fill="x", side="bottom", ipady=12)
        
        # Efectos hover para el botón
        self.btn.bind("<Enter>", lambda e: self.btn.config(bg=C["acento_hover"]) if not self._running else None)
        self.btn.bind("<Leave>", lambda e: self.btn.config(bg=C["acento"]) if not self._running else None)

        # Estado del servidor
        self.lbl_estado = tk.Label(
            left_col, text="Listo para iniciar", bg=C["bg"], fg=C["subtext"],
            font=("Segoe UI", 8)
        )
        self.lbl_estado.pack(fill="x", side="bottom", pady=(0, 8))

        # ── COLUMNA DERECHA (Progreso y Log) ─────────────────────────
        right_col = tk.Frame(body, bg=C["bg"])
        right_col.pack(side="left", fill="both", expand=True)

        # Panel Lote en Proceso
        status_panel = tk.Frame(right_col, bg=C["panel"], bd=1, relief="solid")
        status_panel.pack(fill="x", pady=(0, 15), ipady=8)

        # Detalles del Proceso
        status_detalles = tk.Frame(status_panel, bg=C["panel"], padx=12, pady=4)
        status_detalles.pack(fill="x")
        
        tk.Label(status_detalles, text="Archivo en Proceso:", bg=C["panel"], fg=C["subtext"], font=("Segoe UI", 8)).pack(anchor="w")
        self.lbl_lote = tk.Label(status_detalles, text="Ninguno", bg=C["panel"], fg=C["text"], font=("Segoe UI", 11, "bold"))
        self.lbl_lote.pack(anchor="w", pady=(2, 6))

        tk.Label(status_detalles, text="Paso Actual:", bg=C["panel"], fg=C["subtext"], font=("Segoe UI", 8)).pack(anchor="w")
        self.lbl_paso = tk.Label(status_detalles, text="Esperando instrucciones...", bg=C["panel"], fg=C["warn"], font=("Segoe UI", 10, "bold"))
        self.lbl_paso.pack(anchor="w", pady=(2, 0))

        # Barras de Progreso
        pbar_panel = tk.Frame(status_panel, bg=C["panel"], padx=12)
        pbar_panel.pack(fill="x", pady=(8, 0))

        # Progreso Lote
        lbl_p_lote = tk.Frame(pbar_panel, bg=C["panel"])
        lbl_p_lote.pack(fill="x")
        tk.Label(lbl_p_lote, text="Progreso del lote actual:", bg=C["panel"], fg=C["subtext"], font=("Segoe UI", 8)).pack(side="left")
        self.lbl_pct_lote = tk.Label(lbl_p_lote, text="0%", bg=C["panel"], fg=C["text"], font=("Segoe UI", 8, "bold"))
        self.lbl_pct_lote.pack(side="right")

        s = ttk.Style(self)
        s.theme_use("default")
        s.configure("lote.Horizontal.TProgressbar", troughcolor=C["barra_bg"], background=C["acento"], thickness=8, borderwidth=0)
        self.pbar_lote = ttk.Progressbar(pbar_panel, length=100, maximum=100, style="lote.Horizontal.TProgressbar")
        self.pbar_lote.pack(fill="x", pady=(2, 8))

        # Progreso Global
        lbl_p_global = tk.Frame(pbar_panel, bg=C["panel"])
        lbl_p_global.pack(fill="x")
        tk.Label(lbl_p_global, text="Progreso global (todos los archivos):", bg=C["panel"], fg=C["subtext"], font=("Segoe UI", 8)).pack(side="left")
        self.lbl_pct_global = tk.Label(lbl_p_global, text="0%", bg=C["panel"], fg=C["text"], font=("Segoe UI", 8, "bold"))
        self.lbl_pct_global.pack(side="right")

        s.configure("global.Horizontal.TProgressbar", troughcolor=C["barra_bg"], background=C["ok"], thickness=8, borderwidth=0)
        self.pbar_global = ttk.Progressbar(pbar_panel, length=100, maximum=100, style="global.Horizontal.TProgressbar")
        self.pbar_global.pack(fill="x", pady=(2, 0))

        # Panel de Logs
        log_label_frame = tk.Frame(right_col, bg=C["bg"])
        log_label_frame.pack(fill="x", pady=(0, 4))
        tk.Label(log_label_frame, text="Registro en Tiempo Real (Consola):", bg=C["bg"], fg=C["subtext"], font=("Segoe UI", 9)).pack(side="left")

        self.log = scrolledtext.ScrolledText(
            right_col, bg=C["panel"], fg=C["text"],
            font=("Consolas", 8), insertbackground="white",
            relief="solid", borderwidth=1, highlightthickness=0, wrap="word"
        )
        self.log.pack(fill="both", expand=True)
        self.log.config(state="disabled")

        for tag, color in [("ok", C["ok"]), ("warn", C["warn"]),
                           ("error", C["error"]), ("dim", C["subtext"]), ("info", C["text"])]:
            self.log.tag_config(tag, foreground=color)

    def _truncate_filename(self, filename, max_len=22):
        if len(filename) <= max_len:
            return filename
        idx_dot = filename.rfind('.')
        if idx_dot != -1:
            stem = filename[:idx_dot]
            ext = filename[idx_dot:]
            available = max_len - len(ext) - 3
            if available > 0:
                return stem[:available] + "..." + ext
        return filename[:max_len-3] + "..."

    # ── Fila de estadísticas helper ──────────────────────────────────
    def _create_stat_row(self, parent, text, val_init):
        row = tk.Frame(parent, bg=C["panel"])
        row.pack(fill="x", pady=4)
        tk.Label(row, text=text, bg=C["panel"], fg=C["subtext"], font=("Segoe UI", 9)).pack(side="left")
        val = tk.Label(row, text=val_init, bg=C["panel"], fg=C["acento"], font=("Segoe UI", 9, "bold"))
        val.pack(side="right")
        return val

    # ── Actualizar Estadísticas de BD ─────────────────────────────────
    def _update_db_stats(self):
        stats = {"entities": 0, "batches": 0, "evidence": 0}
        if MASTER_DB.exists():
            try:
                conn = sqlite3.connect(MASTER_DB)
                c = conn.cursor()
                
                c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='master_entities'")
                if c.fetchone():
                    c.execute("SELECT COUNT(*) FROM master_entities")
                    stats["entities"] = c.fetchone()[0]

                c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='processed_batches'")
                if c.fetchone():
                    c.execute("SELECT COUNT(*) FROM processed_batches")
                    stats["batches"] = c.fetchone()[0]

                c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='master_evidence'")
                if c.fetchone():
                    c.execute("SELECT COUNT(*) FROM master_evidence")
                    stats["evidence"] = c.fetchone()[0]
                    
                conn.close()
            except Exception:
                pass

        self.lbl_stat_entities.config(text=str(stats["entities"]))
        self.lbl_stat_batches.config(text=str(stats["batches"]))
        self.lbl_stat_evidence.config(text=str(stats["evidence"]))

    # ── Logging ──────────────────────────────────────────────────────
    def _log(self, msg, tag="info"):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log.config(state="normal")
        self.log.insert("end", f"[{ts}] ", "dim")
        self.log.insert("end", msg + "\n", tag)
        self.log.see("end")
        self.log.config(state="disabled")

    # ── Inicio del pipeline ──────────────────────────────────────────
    def _start(self):
        if self._running:
            return

        # Empaquetar PDFs sueltos primero
        pdfs = list(INPUT_DIR.glob("*.pdf"))
        if pdfs:
            self.after(0, lambda: self._log(f"📄 {len(pdfs)} PDF(s) sueltos detectados. Empaquetando...", "warn"))
            subprocess.run(
                [sys.executable, "-u", str(BASE_DIR / "scripts" / "crear_zip_desde_pdfs.py"), str(INPUT_DIR)],
                capture_output=True, cwd=str(BASE_DIR)
            )

        zips = sorted(INPUT_DIR.glob("*.zip"))
        if not zips:
            messagebox.showwarning(
                "Sin Archivos",
                f"No hay archivos .zip ni .pdf en:\n{INPUT_DIR}\n\n"
                "Coloca tus archivos y vuelve a intentarlo."
            )
            return

        self._zips = zips
        self._errores = []
        self._running = True
        
        self.btn.config(state="disabled", text="⏳  PROCESANDO...", bg=C["barra_bg"])
        self.lbl_estado.config(text="Procesando lote...", fg=C["warn"])
        self.lbl_stat_failed.config(text="Ninguno", fg=C["acento"])
        
        threading.Thread(target=self._pipeline, daemon=True).start()

    # ── Ejecución de Hilo ────────────────────────────────────────────
    def _pipeline(self):
        total = len(self._zips)
        self.after(0, lambda: self._log(f"▶ {total} lote(s) en cola para procesamiento.", "info"))

        for i, zip_path in enumerate(self._zips):
            nombre = zip_path.name
            self.after(0, lambda n=nombre, ii=i: (
                self.lbl_lote.config(text=n),
                self._log(f"━━━ Lote {ii+1}/{total}: {n} ━━━", "info"),
                self._set_progress(0, int(ii / total * 100))
            ))
            ok = self._run_zip(zip_path, i, total)
            if not ok:
                self._errores.append(nombre)

        # Limpiar ZIP temporal si existiese
        tmp = INPUT_DIR / "pdfs_sueltos.zip"
        if tmp.exists():
            tmp.unlink()

        self.after(0, self._finalizar)

    def _run_zip(self, zip_path, idx, total):
        cmd = [
            sys.executable, "-u", "scripts/process_batch.py",
            "--zip_path",   str(zip_path),
            "--master_db",  str(MASTER_DB),
            "--output_dir", str(OUTPUT_DIR),
        ]
        
        if self.var_web.get():
            cmd.append("--enable_web_enrichment")
        if self.var_force.get():
            cmd.append("--force_reprocess_master")

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

        paso_actual_peso = 0
        error_detectado  = False
        lineas_error     = []
        proceso_exitoso  = False

        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                cwd=str(BASE_DIR), encoding="utf-8", errors="replace",
                bufsize=1
            )

            for linea in proc.stdout:
                linea = linea.rstrip()
                if not linea:
                    continue

                if "Errores Detectados: 0" in linea:
                    proceso_exitoso = True

                paso_nombre = None
                for fragmento, peso in PASOS_DETECTADOS:
                    if fragmento in linea:
                        paso_nombre = fragmento.replace("Preparando ", "")
                        paso_actual_peso += peso
                        break

                es_ignorar = any(p in linea for p in PATRON_IGNORAR)
                es_error_real = (not es_ignorar and any(p in linea for p in PATRON_ERROR_REAL))
                if es_error_real:
                    lineas_error.append(linea)
                    error_detectado = True

                pct_lote   = min(int(paso_actual_peso / TOTAL_PESO * 100), 99)
                pct_global = int(((idx + pct_lote / 100) / total) * 100)

                if es_error_real:
                    tag = "error"
                elif any(k in linea for k in ["[OK]", "OK :", ": OK", "exitosa", "éxito", "\u00e9xito"]):
                    tag = "ok"
                elif "OMITIDO" in linea:
                    tag = "dim"
                else:
                    tag = "info"

                self.after(0, lambda l=linea, t=tag, n=paso_nombre, pl=pct_lote, pg=pct_global: (
                    self._log(l, t),
                    self.lbl_paso.config(
                        text=f"⚙  {n}" if n else self.lbl_paso.cget("text"),
                        fg=C["warn"] if n else self.lbl_paso.cget("fg")),
                    self._set_progress(pl, pg)
                ))

            proc.wait()
            rc = proc.returncode

        except Exception as ex:
            rc = -1
            lineas_error = [str(ex)]
            error_detectado = True
            proceso_exitoso = False

        fallo_real = (rc != 0) or (error_detectado and not proceso_exitoso)

        if fallo_real:
            msg_error = "\n".join(lineas_error[-8:]) or f"Código de salida: {rc}"
            self.after(0, lambda z=zip_path.name, e=msg_error: (
                self.lbl_paso.config(text="❌  Error detectado", fg=C["error"]),
                self._log(f"❌ Error procesando '{z}'", "error"),
                self.lbl_stat_failed.config(text=self._truncate_filename(z, 22), fg=C["error"]),
                messagebox.showerror(
                    "Error de Ejecución",
                    f"Hubo un problema al procesar:\n{z}\n\nDetalle:\n{e}\n\nEl pipeline continuará con el siguiente."
                )
            ))
            return False

        self.after(0, lambda z=zip_path.name, ii=idx: (
            self.lbl_paso.config(text="✅  Lote completado", fg=C["ok"]),
            self._log(f"✅ '{z}' — procesado con éxito.", "ok"),
            self._set_progress(100, int(((ii + 1) / total) * 100))
        ))
        return True

    def _set_progress(self, pct_lote, pct_global):
        self.pbar_lote["value"]  = pct_lote
        self.lbl_pct_lote.config(text=f"{pct_lote}%")
        self.pbar_global["value"] = pct_global
        self.lbl_pct_global.config(text=f"{pct_global}%")

    def _finalizar(self):
        self._running = False
        self._update_db_stats()
        
        self.btn.config(state="normal", text="▶  INICIAR PIPELINE", bg=C["acento"])
        n_err = len(self._errores)
        
        if n_err == 0:
            self.lbl_estado.config(text="Completado sin errores", fg=C["ok"])
            self._set_progress(100, 100)
            self._log("══ TODOS LOS ARCHIVOS PROCESADOS EXITOSAMENTE ══", "ok")
            self.lbl_stat_failed.config(text="Ninguno", fg=C["acento"])
            messagebox.showinfo(
                "Proceso Finalizado",
                f"¡Todos los lotes se procesaron exitosamente!\n\nResultados en:\n{OUTPUT_DIR}"
            )
        else:
            resumen = "\n".join(f"• {z}" for z in self._errores)
            self.lbl_estado.config(text=f"Finalizado con {n_err} error(es)", fg=C["error"])
            self._log(f"⚠ Finalizado con {n_err} lote(s) con errores.", "warn")
            
            nombres_cortos = [self._truncate_filename(z, 15) for z in self._errores]
            txt_errores = ", ".join(nombres_cortos)
            if len(txt_errores) > 22:
                txt_errores = txt_errores[:19] + "..."
            self.lbl_stat_failed.config(text=txt_errores, fg=C["error"])
            
            messagebox.showwarning(
                "Finalizado con Errores",
                f"El proceso concluyó. {n_err} lote(s) presentaron problemas:\n\n{resumen}\n\nLos demás se procesaron."
            )

    def _on_close(self):
        if self._running:
            if messagebox.askyesno("Salir", "El procesamiento está activo. ¿Salir de todas formas?"):
                self.destroy()
        else:
            self.destroy()

if __name__ == "__main__":
    app = MonitorApp()
    app.mainloop()
