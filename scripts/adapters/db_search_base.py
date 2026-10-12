import sqlite3
import re
import os

class LocalDBSearcher:
    """Clase base para buscar en el catálogo local de SQLite."""
    
    DB_PATH = "data/external/catalogs.sqlite"
    
    def __init__(self):
        self.conn = None
        if os.path.exists(self.DB_PATH):
            self.conn = sqlite3.connect(self.DB_PATH)
            self.conn.row_factory = sqlite3.Row

    def search_by_name(self, query: str, fuente: str = None, 
                       provincia: str = None, limit: int = 10) -> list:
        """Busca por nombre usando FTS5 para velocidad y relevancia."""
        if not self.conn:
            return []
            
        # Limpiar query para FTS (quitar caracteres especiales)
        clean_query = re.sub(r'[^A-Z0-9\s]', ' ', query.upper()).strip()
        # Convertir a formato FTS: "PALABRA1 PALABRA2 ..."
        # Usamos el operador NEAR para buscar palabras cercanas
        fts_query = " AND ".join([f'"{p}*"' for p in clean_query.split() if len(p) > 2])
        
        if not fts_query:
            return []

        sql = """
            SELECT e.ruc, e.razon_social, e.provincia, e.tipo, e.fuente, rank
            FROM entities_fts f
            JOIN entities e ON f.ruc = e.ruc
            WHERE entities_fts MATCH ?
        """
        params = [fts_query]
        
        if fuente:
            sql += " AND e.fuente = ?"
            params.append(fuente)
            
        if provincia and provincia != "SIN_DATO":
            sql += " AND e.provincia LIKE ?"
            params.append(f"%{provincia.upper()}%")
            
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)
        
        try:
            cursor = self.conn.cursor()
            cursor.execute(sql, params)
            results = []
            for row in cursor.fetchall():
                results.append({
                    "ruc": row["ruc"],
                    "razon_social": row["razon_social"],
                    "provincia": row["provincia"],
                    "estado": "ACTIVO", # Asumimos activo si está en catálogo (mejorar luego)
                    "fuente": row["fuente"],
                    "datos_extra": {"tipo_interno": row["tipo"]}
                })
            return results
        except Exception as e:
            print(f"Error en búsqueda local: {e}")
            return []

    def close(self):
        if self.conn:
            self.conn.close()
