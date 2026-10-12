import sqlite3
import os
import re
from .base import BaseAdapter
from pathlib import Path

class DatasetAdapter(BaseAdapter):
    """
    Adapter enfocado en búsquedas offfline ultra-rápidas usando master catalogs.sqlite.
    Permite matchings exactos o parciales deterministas sin scrapeo buscando en TODO (SRI, SEPS, etc.).
    """
    def __init__(self, db_path=None):
        base_dir = Path(__file__).resolve().parent.parent.parent
        # APUNTAR AL CATALOGO MAESTRO UNIFICADO QUE TIENE SRI, SEPS, AZUAY ETC.
        self.db_path = base_dir / "data" / "external" / "catalogs.sqlite"
        if db_path and Path(db_path).exists() and Path(db_path).name == 'catalogs.sqlite':
            self.db_path = Path(db_path)
            
    def _normalize_for_compare(self, name):
        if not name: return ""
        # Corregir doble codificación UTF-8 común en bases de datos SQLite mal importadas (ej. latin1 codificado como utf8)
        try:
            name = name.encode('latin-1').decode('utf-8')
        except Exception:
            pass
        import unicodedata
        # Remover acentos y eñes (normalizar caracteres especiales españoles)
        name_clean = unicodedata.normalize('NFKD', name.upper())
        name_clean = "".join([c for c in name_clean if not unicodedata.combining(c)])
        # Reducir exclusivamente a cadena de letras y números contiguos
        n = re.sub(r'[^A-Z0-9]', '', name_clean)
        return n

    def _normalize_province(self, prov_name):
        if not prov_name: return ""
        p = prov_name.strip().upper()
        # Mapeo de ciudades/cantones importantes a su provincia correspondiente en Ecuador
        city_to_prov = {
            "QUITO": "PICHINCHA",
            "CUENCA": "AZUAY",
            "GUAYAQUIL": "GUAYAS",
            "PORTOVIEJO": "MANABI",
            "MANTA": "MANABI",
            "LOJA": "LOJA",
            "AMBATO": "TUNGURAHUA",
            "MACHALA": "EL ORO",
            "RIOBAMBA": "CHIMBORAZO",
            "IBARRA": "IMBABURA",
            "LATACUNGA": "COTOPAXI",
            "ESMERALDAS": "ESMERALDAS",
            "BABAHOYO": "LOS RIOS",
            "QUEVEDO": "LOS RIOS",
            "SANTO DOMINGO": "SANTO DOMINGO DE LOS TSÁCHILAS",
            "SANTA ELENA": "SANTA ELENA",
            "SALINAS": "SANTA ELENA",
            "TULCAN": "CARCHI",
            "AZOGUES": "CAÑAR",
            "GUARANDA": "BOLIVAR",
            "PUYO": "PASTAZA",
            "TENA": "NAPO",
            "MACAS": "MORONA SANTIAGO",
            "ZAMORA": "ZAMORA CHINCHIPE",
            "NUEVA LOJA": "SUCUMBIOS",
            "LAGO AGRIO": "SUCUMBIOS",
            "COCA": "ORELLANA",
            "FRANCISCO DE ORELLANA": "ORELLANA"
        }
        
        import unicodedata
        def clean_str(s):
            s_clean = unicodedata.normalize('NFKD', s.upper())
            return "".join([c for c in s_clean if not unicodedata.combining(c)])
            
        p_clean = clean_str(p)
        if p_clean in city_to_prov:
            return clean_str(city_to_prov[p_clean])
        return p_clean

    def _compare_provinces(self, prov_pdf, prov_db):
        if not prov_pdf:
            return "SIN_DATO_ORIGEN"
        p_pdf_norm = self._normalize_province(prov_pdf)
        p_db_norm = self._normalize_province(prov_db)
        if not p_db_norm:
            return "SIN_DATO_DB"
        if p_pdf_norm == p_db_norm or p_pdf_norm in p_db_norm or p_db_norm in p_pdf_norm:
            return "ALTA"
        return "BAJA"

    def _check_sucursal_azuay(self, ruc):
        """Verifica si un RUC tiene sucursal/registro en la provincia de Azuay."""
        if not ruc or not self.db_path.exists():
            return False
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute(
                "SELECT COUNT(*) FROM entities WHERE ruc = ? AND provincia LIKE '%AZUAY%'",
                (ruc,)
            )
            count = c.fetchone()[0]
            conn.close()
            return count > 0
        except Exception:
            return False

    def search(self, name_query, province_query=None):
        if not self.db_path.exists():
            return self._build_result(None, "SIN_RESULTADO_DATASET", "N/A", "N/A", f"Base de datos SQLite no encontrada en {self.db_path}. Recuerda crearla.")

        name_clean = name_query.strip().upper() if name_query else ""
        if not name_clean:
            return self._build_result(None, "SIN_RESULTADO_DATASET", "N/A", "N/A", "Nombre vacío o inválido.")

        prov_clean = province_query
        target_norm = self._normalize_for_compare(name_clean)

        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Buscar MATCH EXACTO usando limpieza on the fly
            # Como indexamos 'razon_social' sin normalizar, el MATCH EXACTO en SQL
            # fallará porque 'CIA.LTDA' vs 'CIALTDA'.
            # Usaremos una aproximación basada en FTS que es igual de veloz pero a prueba de balas.
            
            name_fts = re.sub(r'[^\w\s]', ' ', name_clean)
            # Lista ampliada de exclusión de palabras genéricas corporativas y de ruido
            noise_words = {
                "CIA", "LTDA", "SA", "SAS", "CA", "EP", "CIALTDA", "S.A.", "C.A.", "S.A.S.",
                "COMPANIA", "COMPAÑIA", "COMPANIAS", "COMPAÑIAS", "LIMITADA", "SOCIEDAD", "ANONIMA",
                "ANÓNIMA", "CORPORACION", "CORPORACIÓN", "GRUPO", "DE", "DEL", "EL", "LA", "LOS",
                "Y", "E", "EN", "LIQUIDACION", "LIQUIDACIÓN", "SUCURSAL", "AGENCIA", "ASOCIACION",
                "CONSORCIO", "SERVICIOS", "PRODUCTOS", "ECUADOR", "NACIONAL", "INTERNACIONAL",
                "SUDAMERICA", "PORTAL"
            }
            words = [w for w in name_fts.split() if w not in noise_words]
            
            # Usar las 3 palabras más largas para la búsqueda full-text
            longest_words = sorted(words, key=len, reverse=True)[:3]
            
            if not longest_words:
                # Fallback brutal, usar palabras originales de más de 2 letras
                longest_words = [w for w in name_fts.split() if len(w) > 2][:3]
                
            if longest_words:
                match_q = " ".join([f'"{w}"' for w in longest_words])
                cursor.execute('''
                    SELECT e.* 
                    FROM entities_fts fts
                    JOIN entities e ON fts.ruc = e.ruc
                    WHERE fts.razon_social MATCH ?
                    LIMIT 150
                ''', (match_q,))
                candidate_matches = cursor.fetchall()
            else:
                candidate_matches = []

            # Filtrar en Python los resultados FTS comparando la razón social súper-normalizada
            exact_matches = []
            for r in candidate_matches:
                db_norm = self._normalize_for_compare(r['razon_social'])
                # Si el texto detectado por el LLM está completamente contenido en el de la DB
                # o viceversa (por cosas como CIALTDA vs CIA LTDA)
                if target_norm == db_norm or target_norm in db_norm or db_norm in target_norm:
                    exact_matches.append(r)
            
            if exact_matches:
                if len(exact_matches) == 1:
                    row = exact_matches[0]
                    prov_db = row["provincia"].upper() if row["provincia"] else ""
                    match_prov = self._compare_provinces(prov_clean, prov_db)
                    
                    # Para match exacto único, no castigar por provincia ya que puede ser sucursal o error en PDF
                    estado = "COINCIDENCIA_DATASET_LOCAL_ALTA"
                    obs = f"Coincidencia exacta en catálogo ({row['fuente']})."
                    
                    return self._build_result(row["ruc"], estado, "ALTA", match_prov, obs, provincia_oficial=prov_db)
                    
                elif len(exact_matches) > 1:
                    # Desempatar por provincia
                    candidatos_provincia = []
                    for r in exact_matches:
                        prov_db = r["provincia"].upper() if r["provincia"] else ""
                        match_prov = self._compare_provinces(prov_clean, prov_db)
                        if match_prov == "ALTA":
                            candidatos_provincia.append(r)
                            
                    if len(candidatos_provincia) == 1:
                        row = candidatos_provincia[0]
                        prov_db = row["provincia"].upper() if row["provincia"] else ""
                        return self._build_result(row["ruc"], "COINCIDENCIA_DATASET_LOCAL_ALTA", "ALTA", "ALTA", f"Múltiples empresas idénticas: Desempate por provincia ({row['fuente']}).", provincia_oficial=prov_db)
                    elif len(candidatos_provincia) > 1:
                        return self._build_result(None, "AMBIGUO_DATASET_LOCAL", "ALTA", "AMBIGUO", f"Existen {len(candidatos_provincia)} empresas con idéntico nombre EN LA MISMA PROVINCIA.")
                    else:
                        return self._build_result(None, "AMBIGUO_DATASET_LOCAL", "ALTA", "AMBIGUO", f"Existen {len(exact_matches)} empresas con idéntico nombre en diferentes provincias.")

            # Si llegamos aquí no hubo un exacto en los FTS, pero vamos a ver si hubo un match parcial decente
            # Devolvemos el primero de `candidate_matches` si pasa el filtro de coincidencia de tokens core
            if len(candidate_matches) == 1:
                 row = candidate_matches[0]
                 if self._is_valid_name_match(name_clean, row['razon_social']):
                      prov_db = row["provincia"].upper() if row["provincia"] else ""
                      return self._build_result(row["ruc"], "COINCIDENCIA_DATASET_LOCAL_MEDIA", "MEDIA", "N/A", f"Búsqueda aproximada exitosa ({row['fuente']}).", provincia_oficial=prov_db)
                 else:
                      return self._build_result(None, "SIN_RESULTADO_DATASET", "BAJA", "N/A", "El candidato único devuelto por FTS no coincide en palabras clave.")
            elif len(candidate_matches) > 1:
                 # Filtrar candidatos que sí coinciden a nivel de core tokens
                 valid_candidates = [r for r in candidate_matches if self._is_valid_name_match(name_clean, r['razon_social'])]
                 if len(valid_candidates) == 1:
                      row = valid_candidates[0]
                      prov_db = row["provincia"].upper() if row["provincia"] else ""
                      return self._build_result(row["ruc"], "COINCIDENCIA_DATASET_LOCAL_MEDIA", "MEDIA", "N/A", f"Búsqueda aproximada única tras depuración ({row['fuente']}).", provincia_oficial=prov_db)
                 else:
                      return self._build_result(None, "AMBIGUO_DATASET_LOCAL", "MEDIA", "N/A", f"Búsqueda aproximada: Múltiples opciones parecidas detectadas.")

            return self._build_result(None, "SIN_RESULTADO_DATASET", "BAJA", "N/A", "A pesar de buscar en TODO el catálogo nacional, no hubo rastro ni parecido.")
            
        except Exception as e:
            return self._build_result(None, "SIN_RESULTADO_DATASET", "N/A", "N/A", f"Error de lectura SQLite FTS: {e}")
        finally:
            if 'conn' in locals():
                conn.close()
            
    def _is_valid_name_match(self, query_name, db_name):
        if not query_name or not db_name:
            return False
            
        # Corregir doble codificación en db_name para comparar limpio
        try:
            db_name_clean = db_name.encode('latin-1').decode('utf-8')
        except Exception:
            db_name_clean = db_name

        def get_core_tokens(name):
            n = re.sub(r'[^A-Z0-9\s]', ' ', name.upper())
            tokens = n.split()
            noise = {
                "CIA", "LTDA", "SA", "SAS", "CA", "EP", "CIALTDA", "S.A.", "C.A.", "S.A.S.",
                "COMPANIA", "COMPAÑIA", "COMPANIAS", "COMPAÑIAS", "LIMITADA", "SOCIEDAD", "ANONIMA",
                "ANÓNIMA", "CORPORACION", "CORPORACIÓN", "GRUPO", "DE", "DEL", "EL", "LA", "LOS",
                "Y", "E", "EN", "LIQUIDACION", "LIQUIDACIÓN", "SUCURSAL", "AGENCIA", "ASOCIACION",
                "CONSORCIO", "SERVICIOS", "PRODUCTOS", "ECUADOR", "NACIONAL", "INTERNACIONAL",
                "SUDAMERICA", "PORTAL"
            }
            return [t for t in tokens if t not in noise and len(t) > 2]

        q_tokens = get_core_tokens(query_name)
        db_tokens = get_core_tokens(db_name_clean)
        
        if not q_tokens:
            return False
            
        matched_count = 0
        for qt in q_tokens:
            if any(qt in dbt or dbt in qt for dbt in db_tokens):
                matched_count += 1
                
        return matched_count > 0

    def _build_result(self, ruc, estado, match_name, match_prov, obs, provincia_oficial=None):
        tiene_azuay = self._check_sucursal_azuay(ruc) if ruc else False
        return {
            "ruc_final": ruc,
            "estado_resolucion": estado,
            "fuente_consultada": "CATALOGO_UNIFICADO_LOCAL",
            "coincidencia_nombre": match_name,
            "coincidencia_provincia": match_prov,
            "provincia_oficial": provincia_oficial,
            "sucursal_azuay": "SI" if tiene_azuay else "NO",
            "observaciones": obs
        }
