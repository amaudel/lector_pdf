import os
import csv
import json
import argparse
from pathlib import Path

def get_establishments_for_rucs(rucs_set, external_dir):
    import glob
    from pathlib import Path
    
    # Map RUC -> set of establishment strings (e.g., "001", "002")
    ruc_to_est = {ruc: set() for ruc in rucs_set}
    
    # Use set() to avoid duplicates from overlapping glob matches in case-insensitive environments like Windows
    csv_files = set(glob.glob(str(external_dir / "SRI_RUC_*.csv")) + glob.glob(str(external_dir / "sri_ruc_*.csv")))
    
    for csv_file in csv_files:
        print(f"[*] Escaneando {Path(csv_file).name} para sucursales...")
        try:
            with open(csv_file, 'r', encoding='latin1', errors='ignore') as f:
                headers = f.readline().strip().split('|')
                # Encontrar indices de columnas
                try:
                    ruc_idx = headers.index('NUMERO_RUC')
                    est_idx = headers.index('NUMERO_ESTABLECIMIENTO')
                except ValueError:
                    print(f"  [!] No se encontraron las columnas requeridas en {Path(csv_file).name}")
                    continue
                
                for line in f:
                    # Búsqueda rápida de subcadena antes de hacer split
                    # Esto evita hacer split en líneas que no contienen ninguno de nuestros RUCs
                    if not any(ruc in line for ruc in rucs_set):
                        continue
                        
                    parts = line.strip().split('|')
                    if len(parts) > max(ruc_idx, est_idx):
                        ruc_val = parts[ruc_idx].strip()
                        if ruc_val in rucs_set:
                            est_val = parts[est_idx].strip()
                            try:
                                # Asegurar que sea de 3 dígitos con ceros a la izquierda
                                est_int = int(est_val)
                                est_str = f"{est_int:03d}"
                                ruc_to_est[ruc_val].add(est_str)
                            except ValueError:
                                pass
        except Exception as e:
            print(f"  [!] Error leyendo {Path(csv_file).name}: {e}")
            
    # Convertir sets a listas ordenadas separadas por coma
    result = {}
    for ruc, est_set in ruc_to_est.items():
        if est_set:
            result[ruc] = ", ".join(sorted(list(est_set)))
        else:
            result[ruc] = "001" # Fallback por defecto si no se encuentra en el padrón local
            
    return result

def update_master_excel(records, master_excel_path):
    import pandas as pd
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    
    # 1. Definir columnas del Excel Maestro
    columns = [
        "Nro", "MEMORANDO INICIAL", "MEMORANDO DP", "SOLICITANTE",
        "RAZÓN SOCIAL", "RUC", "SUCURSAL", "RESOLUCIÓN",
        "PROVINCIA", "ACCIONES", "OBSERVACIONES"
    ]
    
    # 2. Leer registros existentes o iniciar vacío
    if master_excel_path.exists():
        try:
            df_master = pd.read_excel(master_excel_path, sheet_name="Master", dtype={"RUC": str})
            # Asegurar columnas correctas
            for col in columns:
                if col not in df_master.columns:
                    df_master[col] = ""
            df_master = df_master[columns]
        except Exception as e:
            print(f"[!] Error leyendo Excel acumulado existente: {e}. Se creará uno nuevo.")
            df_master = pd.DataFrame(columns=columns)
    else:
        df_master = pd.DataFrame(columns=columns)
        
    # Determinar el último número secuencial Nro
    if not df_master.empty:
        try:
            last_nro = pd.to_numeric(df_master["Nro"], errors='coerce').max()
            if pd.isna(last_nro):
                last_nro = 0
            else:
                last_nro = int(last_nro)
        except Exception:
            last_nro = len(df_master)
    else:
        last_nro = 0
        
    # 3. Transformar nuevos registros para el formato Maestro
    new_rows = []
    
    # Pre-calcular memorando inicial y dp a nivel del lote
    batch_memo_inicial = ""
    batch_memo_dp = ""
    
    # 1. Buscar en data/input/ (archivos físicos sueltos)
    try:
        input_dir = Path("data/input")
        if input_dir.exists():
            for pdf_path in input_dir.glob("*.pdf"):
                name = pdf_path.stem.upper()
                if "SDNGC" in name:
                    batch_memo_inicial = name
                elif "DPAZUAY" in name or "DP-AZUAY" in name or "IESS-DP" in name or "INT-DP" in name:
                    batch_memo_dp = name
    except Exception as e:
        print(f"[!] Error buscando memorandos sueltos en data/input: {e}")
        
    # 2. Fallback/Refuerzo: buscar en los archivos_origen de los registros
    for rec in records:
        archivos_str = rec.get("archivos_origen", "")
        for a in archivos_str.split("|"):
            a_clean = a.strip()
            if not a_clean:
                continue
            if a_clean.lower().endswith(".pdf"):
                a_clean = a_clean[:-4]
            a_up = a_clean.upper()
            if not batch_memo_inicial and "SDNGC" in a_up:
                batch_memo_inicial = a_up
            elif not batch_memo_dp and ("DPAZUAY" in a_up or "DP-AZUAY" in a_up or "IESS-DP" in a_up or "INT-DP" in a_up):
                batch_memo_dp = a_up
                
    for rec in records:
        archivos_str = rec.get("archivos_origen", "")
        archivos_list = [a.strip() for a in archivos_str.split("|") if a.strip()]
        
        # Identificar resoluciones (archivos que no son memorandos)
        resoluciones = []
        for a in archivos_list:
            if a.lower().endswith(".pdf"):
                a = a[:-4]
            a_up = a.upper()
            if "IESS-SDNGC" not in a_up and "IESS-DP" not in a_up and "SDNGC" not in a_up and "DPAZUAY" not in a_up:
                resoluciones.append(a_up)
                
        resolucion_str = " | ".join(resoluciones)
        
        # Fallback si no logramos identificar el inicial/dp a nivel de lote
        archivos_clean = []
        for a in archivos_list:
            if a.lower().endswith(".pdf"):
                a = a[:-4]
            archivos_clean.append(a.upper())
            
        m_inicial = batch_memo_inicial if batch_memo_inicial else (" | ".join(archivos_clean))
        m_dp = batch_memo_dp if batch_memo_dp else ""
        
        ruc = str(rec.get("ruc_final", ""))
        if ruc == "SIN_DATO":
            ruc = ""
            
        provincia = str(rec.get("provincia_final", ""))
        if provincia == "SIN_DATO":
            provincia = ""
            
        sucursal = str(rec.get("sucursal", ""))
        
        last_nro += 1
        new_row = {
            "Nro": last_nro,
            "MEMORANDO INICIAL": m_inicial,
            "MEMORANDO DP": m_dp,
            "SOLICITANTE": "",
            "RAZÓN SOCIAL": str(rec.get("razon_social_final", "")).upper(),
            "RUC": ruc,
            "SUCURSAL": sucursal,
            "RESOLUCIÓN": resolucion_str,
            "PROVINCIA": provincia.upper(),
            "ACCIONES": "",
            "OBSERVACIONES": ""
        }
        new_rows.append(new_row)
        
    df_new = pd.DataFrame(new_rows, columns=columns)
    
    # 4. Concatenar
    df_result = pd.concat([df_master, df_new], ignore_index=True)
    df_result = df_result.fillna("")
    
    # Asegurar que RUC y Nro no contengan decimales .0 ni strings 'nan'
    def clean_ruc(val):
        if val is None:
            return ""
        s = str(val).strip()
        if s.endswith(".0"):
            s = s[:-2]
        if s.lower() in ["nan", "none", "sin_dato", ""]:
            return ""
        return s
        
    def clean_nro(val):
        if val is None:
            return ""
        s = str(val).strip()
        if s.endswith(".0"):
            s = s[:-2]
        if s.lower() in ["nan", "none", ""]:
            return ""
        return s

    df_result["RUC"] = df_result["RUC"].apply(clean_ruc)
    df_result["Nro"] = df_result["Nro"].apply(clean_nro)
    
    # 5. Escribir archivo con estilos premium y protección de bloqueo
    written = False
    for i in range(11):
        target_path = master_excel_path if i == 0 else master_excel_path.parent / f"reporte_acumulado_{i}.xlsx"
        try:
            with pd.ExcelWriter(target_path, engine='openpyxl') as writer:
                df_result.to_excel(writer, index=False, sheet_name="Master")
                wb = writer.book
                ws = writer.sheets["Master"]
                
                col_colors = {
                    1: 'FCE4D6', # Nro
                    2: 'D9E1F2', # MEMORANDO INICIAL
                    3: 'D9E1F2', # MEMORANDO DP
                    4: 'E7E6E6', # SOLICITANTE
                    5: 'F8CBAD', # RAZÓN SOCIAL
                    6: 'F8CBAD', # RUC
                    7: 'BDD7EE', # SUCURSAL
                    8: 'BDD7EE', # RESOLUCIÓN
                    9: '5B9BD5', # PROVINCIA
                    10: 'C6E0B4', # ACCIONES
                    11: 'C65911'  # OBSERVACIONES
                }
                
                header_font = Font(name='Calibri', bold=True, color='000000', size=11)
                header_font_white = Font(name='Calibri', bold=True, color='FFFFFF', size=11)
                
                header_align = Alignment(horizontal='center', vertical='center', wrap_text=True)
                cell_align = Alignment(vertical='center', wrap_text=False)
                cell_align_left = Alignment(horizontal='left', vertical='center', wrap_text=False)
                cell_align_center = Alignment(horizontal='center', vertical='center', wrap_text=False)
                
                thin_border = Border(
                    left=Side(style='thin', color='7F7F7F'),
                    right=Side(style='thin', color='7F7F7F'),
                    top=Side(style='thin', color='7F7F7F'),
                    bottom=Side(style='thin', color='7F7F7F')
                )
                
                for col_idx in range(1, 12):
                    cell = ws.cell(row=1, column=col_idx)
                    if col_idx in [9, 11]:
                        cell.font = header_font_white
                    else:
                        cell.font = header_font
                        
                    color = col_colors.get(col_idx, 'D9D9D9')
                    cell.fill = PatternFill(start_color=color, end_color=color, fill_type='solid')
                    cell.alignment = header_align
                    cell.border = thin_border
                    
                for row_idx in range(2, len(df_result) + 2):
                    for col_idx in range(1, 12):
                        cell = ws.cell(row=row_idx, column=col_idx)
                        cell.font = Font(name='Calibri', size=10)
                        cell.border = thin_border
                        
                        if col_idx in [1, 6, 7, 9]:
                            cell.alignment = cell_align_center
                        elif col_idx in [2, 5]:
                            cell.alignment = cell_align_left
                        else:
                            cell.alignment = cell_align
                            
                        if col_idx in [5, 6, 9]:
                            cell.fill = PatternFill(start_color='FFF2CC', end_color='FFF2CC', fill_type='solid')
                            
                        if col_idx in [6, 7]:
                            cell.number_format = '@'
                            
                from openpyxl.utils import get_column_letter
                for col_idx in range(1, 12):
                    col_letter = get_column_letter(col_idx)
                    max_length = len(str(ws.cell(row=1, column=col_idx).value))
                    for row_idx in range(2, len(df_result) + 2):
                        val = ws.cell(row=row_idx, column=col_idx).value
                        if val is not None:
                            max_length = max(max_length, len(str(val)))
                    ws.column_dimensions[col_letter].width = min(max_length + 4, 50)
                    
                ws.freeze_panes = 'A2'
                ws.row_dimensions[1].height = 28
                
                for row_idx in range(2, len(df_result) + 2):
                    ws.row_dimensions[row_idx].height = 20
                    
            print(f"[*] Excel acumulado maestro actualizado exitosamente en: {target_path}")
            written = True
            break
        except PermissionError:
            print(f"[!] Archivo maestro bloqueado por Excel o en uso: {target_path.name}. Reintentando...")
            continue
            
    if not written:
        print("[X] ERROR CRÍTICO: No se pudo actualizar el Excel acumulado maestro porque está bloqueado.")

def generate_business_export(resolved_path, output_dir, mode='batch'):
    if mode == 'master':
        print("[!] Modo 'master' (exportación global desde SQLite) en construcción. Abortando exportación...")
        return
        
    resolved_file = Path(resolved_path)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # Derivar Lote Base
    filename = resolved_file.name
    lote_base = filename.replace("resolved_", "").replace(".jsonl", "")
    
    csv_path = out_dir / f"resultado_final_{lote_base}.csv"
    json_path = out_dir / f"resultado_final_{lote_base}.json"
    
    manual_file = out_dir / f"manual_review_{lote_base}.jsonl"
    web_enriched_file = out_dir / f"web_enriched_{lote_base}.jsonl"
    
    files_to_read = []
    if resolved_file.exists(): files_to_read.append(resolved_file)
    if manual_file.exists(): files_to_read.append(manual_file)
    
    # Cargar enriquecimiento web si existe
    web_lookup = {}
    if web_enriched_file.exists():
        print(f"[*] Detectado archivo de enriquecimiento web: {web_enriched_file.name}. Cargando RUCs web...")
        try:
            with open(web_enriched_file, 'r', encoding='utf-8') as f_web:
                for line in f_web:
                    if line.strip():
                        w_data = json.loads(line)
                        ruc_enc = w_data.get("ruc_encontrado")
                        if ruc_enc and ruc_enc != "SIN_DATO":
                            name_orig = w_data.get("razon_social_pdf_original")
                            name_pdf = w_data.get("razon_social_pdf")
                            val = {
                                "ruc": ruc_enc,
                                "razon_social_web": w_data.get("razon_social_web"),
                                "provincia_web": w_data.get("provincia_web"),
                                "estado_web": w_data.get("estado_web"),
                                "score": w_data.get("score_confianza", 0.0),
                                "adapter": w_data.get("adapter_usado") or w_data.get("fuente", "WEB")
                            }
                            if name_orig:
                                web_lookup[name_orig.strip().upper()] = val
                            if name_pdf:
                                web_lookup[name_pdf.strip().upper()] = val
            print(f"[*] Se cargaron {len(web_lookup)} empresas resueltas vía web.")
        except Exception as e:
            print(f"[!] Error leyendo enriquecimiento web: {e}")
            
    # Primera pasada: Recolectar todos los RUCs finales para consulta de sucursales en lote
    rucs_to_query = set()
    raw_records_data = []
    for current_file in files_to_read:
        with open(current_file, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    raw_records_data.append(data)
                    
                    candidato = data.get("candidato_original", {})
                    ruc = data.get("ruc_final", "SIN_DATO")
                    if not ruc: ruc = "SIN_DATO"
                    
                    # Pre-resolver RUC de web si no está directo en ruc_final
                    if not ruc or ruc == "SIN_DATO":
                        cand_name_upper = ""
                        if candidato:
                            cand_name_orig = candidato.get("razon_social_original")
                            if cand_name_orig: cand_name_upper = cand_name_orig.strip().upper()
                        if not cand_name_upper:
                            cand_name_cand = data.get("razon_social_candidata")
                            if cand_name_cand: cand_name_upper = cand_name_cand.strip().upper()
                        
                        if cand_name_upper and cand_name_upper in web_lookup:
                            ruc = web_lookup[cand_name_upper]["ruc"]
                            
                    if ruc and ruc != "SIN_DATO" and len(ruc) == 13:
                        rucs_to_query.add(ruc)
                except Exception:
                    pass
                    
    # Buscar sucursales/establecimientos en el padrón local
    root_dir = Path(__file__).resolve().parent.parent
    external_dir = root_dir / "data" / "external"
    establishments_map = {}
    if rucs_to_query:
        establishments_map = get_establishments_for_rucs(rucs_to_query, external_dir)
        
    records = []
    
    for data in raw_records_data:
        candidato = data.get("candidato_original", {})
        estado_res = data.get("estado_resolucion", "DESCONOCIDO")
        
        # 1. Determinar Reglas de Provincia
        provincia_oficial = "SIN_DATO"
        fuente_provincia = "N/A"
        if data.get("provincia_oficial") and data.get("provincia_oficial") != "SIN_DATO":
            provincia_oficial = data["provincia_oficial"]
            fuente_provincia = "DATASET_OFICIAL"
        elif "dataset_match" in data and data["dataset_match"] and data["dataset_match"].get("provincia"):
            provincia_oficial = data["dataset_match"]["provincia"]
            fuente_provincia = "DATASET_OFICIAL"
        elif candidato.get("provincia_mencionada") and candidato.get("provincia_mencionada") != "SIN_DATO":
            provincia_oficial = candidato.get("provincia_mencionada")
            fuente_provincia = "TEXTO_PDF"
            
        # 2. Determinar Reglas de RUC
        ruc = data.get("ruc_final", "SIN_DATO")
        if not ruc: ruc = "SIN_DATO"
        fuente_ruc = data.get("fuente_ruc") or "N/A"
        
        observaciones = []
        
        # Intentar enriquecimiento web si el RUC actual está vacío o no resuelto
        if not ruc or ruc == "SIN_DATO":
            cand_name_upper = ""
            if candidato:
                cand_name_orig = candidato.get("razon_social_original")
                if cand_name_orig:
                    cand_name_upper = cand_name_orig.strip().upper()
                    
            if not cand_name_upper:
                cand_name_cand = data.get("razon_social_candidata")
                if cand_name_cand:
                    cand_name_upper = cand_name_cand.strip().upper()
            
            if cand_name_upper and cand_name_upper in web_lookup:
                web_info = web_lookup[cand_name_upper]
                ruc = web_info["ruc"]
                fuente_ruc = f"WEB_{web_info['adapter']}"
                observaciones.append(f"Resuelto vía web ({web_info['adapter']}): {web_info['razon_social_web']} (confianza: {web_info['score']}).")
                
                # Si no hay provincia oficial, heredar de la web
                if (not provincia_oficial or provincia_oficial == "SIN_DATO") and web_info["provincia_web"]:
                    provincia_oficial = web_info["provincia_web"]
                    fuente_provincia = f"WEB_{web_info['adapter']}"
        
        # 3. Determinar Revisión Manual
        estados_requieren_revision = ["REVISION_MANUAL", "AMBIGUO_DATASET_LOCAL", "AMBIGUO_EXTERNAMENTE", "SIN_RESULTADO_EXTERNO"]
        requiere_revision = "SI" if estado_res in estados_requieren_revision else "NO"
        
        # Si se resolvió por web, marcar que requiere revisión (es lo más seguro ya que es dato externo/web)
        if fuente_ruc and fuente_ruc.startswith("WEB_"):
            requiere_revision = "SI"
        
        # 4. Generar Observaciones inteligentes
        if requiere_revision == "SI":
            if ruc == "SIN_DATO":
                observaciones.append("No se detectó RUC y no hubo coincidencia externa clara.")
            else:
                if not fuente_ruc.startswith("WEB_"):
                    observaciones.append("Requiere revisión humana por evidencia débil o ambigua.")
        elif estado_res == "COINCIDENCIA_DATASET_LOCAL_MEDIA":
            observaciones.append("Coincidencia parcial. Revisar exactitud del nombre corporativo.")
        elif estado_res == "RUC_EXTRAIDO_DEL_PDF":
            observaciones.append("Alta confianza. RUC explícito en el documento.")
        elif "DATASET_LOCAL_ALTA" in estado_res:
            observaciones.append("Alta confianza. Validación en Padrón Oficial.")
            
        # Consolidar orígenes para fácil lectura
        archivos = set(candidato.get("archivos_origen", []))
        paginas = sorted(list(set(candidato.get("paginas_origen", []))))
        
        sucursal_azuay = data.get("sucursal_azuay", "NO")
        
        # Fallback: si la provincia ya es Azuay, marcar sucursal como SI
        # (cubre casos donde el RUC no fue encontrado pero la provincia sí)
        if "AZUAY" in provincia_oficial.upper():
            sucursal_azuay = "SI"
        
        sucursal = ""
        if ruc and ruc != "SIN_DATO" and len(ruc) == 13:
            sucursal = establishments_map.get(ruc, "001")
            
        record = {
            "lote": lote_base,
            "razon_social_final": data.get("razon_social_candidata", "DESCONOCIDA"),
            "ruc_final": ruc,
            "sucursal": sucursal,
            "provincia_final": provincia_oficial,
            "sucursal_azuay": sucursal_azuay,
            "tipo_entidad": candidato.get("tipo_entidad_detectada", "DESCONOCIDO"),
            "estado_final": estado_res,
            "fuente_ruc": fuente_ruc,
            "fuente_provincia": fuente_provincia,
            "archivos_origen": " | ".join(archivos),
            "paginas_origen": ", ".join(map(str, paginas)),
            "requiere_revision": requiere_revision,
            "observaciones": " ".join(observaciones)
        }
        records.append(record)
            
    # Escritura Excel profesional
    import pandas as pd
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    
    COLUMN_LABELS = {
        "lote": "Lote",
        "razon_social_final": "Razón Social",
        "ruc_final": "RUC",
        "sucursal": "Sucursal",
        "provincia_final": "Provincia",
        "sucursal_azuay": "Sucursal en Azuay",
        "tipo_entidad": "Tipo Entidad",
        "estado_final": "Estado de Resolución",
        "fuente_ruc": "Fuente del RUC",
        "fuente_provincia": "Fuente Provincia",
        "archivos_origen": "Archivos Origen (PDF)",
        "paginas_origen": "Páginas",
        "requiere_revision": "¿Requiere Revisión?",
        "observaciones": "Observaciones"
    }
    
    fieldnames = list(COLUMN_LABELS.keys())
    
    # Carpeta específica para reportes Excel (Petición del usuario)
    excel_report_dir = out_dir / "REPORTES DE EXCEL"
    excel_report_dir.mkdir(parents=True, exist_ok=True)
    
    excel_path = excel_report_dir / f"resultado_final_{lote_base}.xlsx"
    df = pd.DataFrame(records, columns=fieldnames)
    df = df.fillna("")  # Limpiar NaN para que no rompa nada
    
    # Renombrar columnas a etiquetas humanas
    df.rename(columns=COLUMN_LABELS, inplace=True)
    
    written_successfully = False
    for i in range(11):
        if i == 0:
            target_path = excel_path
        else:
            target_path = excel_report_dir / f"resultado_final_{lote_base}_{i}.xlsx"
            
        try:
            with pd.ExcelWriter(target_path, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name="Resultados")
                wb = writer.book
                ws = writer.sheets["Resultados"]
                
                # Estilos
                header_font = Font(name='Calibri', bold=True, color='FFFFFF', size=11)
                header_fill = PatternFill(start_color='2F5496', end_color='2F5496', fill_type='solid')
                header_align = Alignment(horizontal='center', vertical='center', wrap_text=True)
                cell_align = Alignment(vertical='top', wrap_text=True)
                thin_border = Border(
                    left=Side(style='thin', color='D9D9D9'),
                    right=Side(style='thin', color='D9D9D9'),
                    top=Side(style='thin', color='D9D9D9'),
                    bottom=Side(style='thin', color='D9D9D9')
                )
                revision_si_fill = PatternFill(start_color='FFF2CC', end_color='FFF2CC', fill_type='solid')
                ok_fill = PatternFill(start_color='E2EFDA', end_color='E2EFDA', fill_type='solid')
                azuay_fill = PatternFill(start_color='00B0F0', end_color='00B0F0', fill_type='solid')  # Azul AZUAY
                
                # Aplicar estilos al encabezado
                for col_idx in range(1, len(df.columns) + 1):
                    cell = ws.cell(row=1, column=col_idx)
                    cell.font = header_font
                    cell.fill = header_fill
                    cell.alignment = header_align
                    cell.border = thin_border
                
                # Índices de columnas clave para colorear
                rev_col_idx = list(df.columns).index("¿Requiere Revisión?") + 1 if "¿Requiere Revisión?" in df.columns else None
                azuay_col_idx = list(df.columns).index("Sucursal en Azuay") + 1 if "Sucursal en Azuay" in df.columns else None
                
                ruc_col_idx = list(df.columns).index("RUC") + 1 if "RUC" in df.columns else None
                suc_col_idx = list(df.columns).index("Sucursal") + 1 if "Sucursal" in df.columns else None
                
                for row_idx in range(2, len(df) + 2):
                    for col_idx in range(1, len(df.columns) + 1):
                        cell = ws.cell(row=row_idx, column=col_idx)
                        cell.alignment = cell_align
                        cell.border = thin_border
                        cell.font = Font(name='Calibri', size=10)
                        
                        if col_idx in [ruc_col_idx, suc_col_idx]:
                            cell.number_format = '@'
                            cell.alignment = Alignment(horizontal='center', vertical='top', wrap_text=True)
                    
                    # Colorear fila según estado de revisión
                    if rev_col_idx:
                        rev_value = ws.cell(row=row_idx, column=rev_col_idx).value
                        row_fill = revision_si_fill if rev_value == "SI" else ok_fill
                        for col_idx in range(1, len(df.columns) + 1):
                            ws.cell(row=row_idx, column=col_idx).fill = row_fill
                    
                    # Colorear celda de Azuay en azul brillante si tiene sucursal
                    if azuay_col_idx:
                        azuay_value = ws.cell(row=row_idx, column=azuay_col_idx).value
                        if azuay_value == "SI":
                            cell = ws.cell(row=row_idx, column=azuay_col_idx)
                            cell.fill = azuay_fill
                            cell.font = Font(name='Calibri', size=10, bold=True, color='FFFFFF')
                
                # Auto-ajustar anchos de columna
                for col_idx in range(1, len(df.columns) + 1):
                    col_letter = get_column_letter(col_idx)
                    max_length = len(str(ws.cell(row=1, column=col_idx).value))  # Empezar con el header
                    for row_idx in range(2, len(df) + 2):
                        val = ws.cell(row=row_idx, column=col_idx).value
                        if val is not None:
                            max_length = max(max_length, len(str(val)))
                    ws.column_dimensions[col_letter].width = min(max_length + 3, 45)
                
                # Congelar la fila del encabezado (así el usuario puede hacer scroll sin perderlo)
                ws.freeze_panes = 'A2'
                
                # Altura de fila del header
                ws.row_dimensions[1].height = 30
                
            excel_path = target_path
            written_successfully = True
            break
        except PermissionError:
            print(f"[!] Archivo bloqueado por Excel o en uso: {target_path.name}. Intentando ruta alternativa...")
            continue
            
    if not written_successfully:
        print("[X] No se pudo escribir el archivo Excel tras 10 intentos. Asegúrese de cerrar Excel.")
        return

    # Escritura JSON Analítico
    with open(json_path, 'w', encoding='utf-8') as jsonfile:
        json.dump({"lote": lote_base, "total_registros": len(records), "resultados": records}, jsonfile, ensure_ascii=False, indent=2)
        
    # Actualizar Excel Acumulado Maestro (Petición especial)
    root_dir = Path(__file__).resolve().parent.parent
    master_excel_path = root_dir / "reporte_acumulado.xlsx"
    update_master_excel(records, master_excel_path)
        
    print(f"=========================================")
    print(f" EXPORTACIÓN DE RESULTADOS BATCH (PASO 9)")
    print(f"=========================================")
    print(f" Lote exportado    : {lote_base}")
    print(f" Total procesados  : {len(records)}")
    print(f" Req. Revisiones   : {sum(1 for r in records if r['requiere_revision'] == 'SI')}")
    print(f" RUCs Exitosos     : {sum(1 for r in records if r['ruc_final'] != 'SIN_DATO')}")
    print(f"-----------------------------------------")
    print(f"[*] EXCEL Guardado : REPORTES DE EXCEL/{excel_path.name}")
    print(f"[*] JSON Guardado  : {json_path.name}")
    print(f"=========================================")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Paso 9: Exportador final para analistas operativos (Excel/JSON)")
    parser.add_argument("--resolved_path", help="Ruta al archivo resolved_[lote].jsonl (Paso 7)")
    parser.add_argument("--output_dir", required=True, help="Ruta a la carpeta de salidas")
    parser.add_argument("--mode", default="batch", choices=["batch", "master"], help="Modo operativo")
    
    args = parser.parse_args()
    if args.mode == "batch" and not args.resolved_path:
        parser.error("--resolved_path es requerido cuando el modo es 'batch'")
        
    generate_business_export(args.resolved_path, args.output_dir, args.mode)
