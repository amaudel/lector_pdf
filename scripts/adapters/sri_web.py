"""
Adapter REAL para SRI (Servicio de Rentas Internas).
Consulta el catálogo local de catastros descargados en modo MOCK/local, o realiza una búsqueda web real en modo REAL.
"""
from .web_base import WebAdapter
from .db_search_base import LocalDBSearcher
import re

class SriWebAdapter(WebAdapter):
    """
    Adapter SRI para enriquecimiento.
    En modo REAL realiza búsquedas en DuckDuckGo + extracción con GPT-4o-mini.
    En modo MOCK realiza búsquedas locales en la base SQLite.
    """
    
    FUENTE = "SRI"
    
    def __init__(self, modo: str = "REAL"):
        super().__init__(modo)
        self.searcher = LocalDBSearcher()

    def search(self, razon_social: str, provincia: str = None,
               tipo_entidad: str = None) -> list:
        """Busca contribuyentes en la web o en la base real del SRI."""
        if self.modo == "REAL":
            query = f"RUC {razon_social} Ecuador"
            candidatos = self._search_web_and_extract(query, razon_social)
            
            enriquecidos = []
            for res in candidatos:
                enriquecidos.append({
                    "ruc": res["ruc"],
                    "razon_social": res["razon_social"],
                    "provincia": res.get("provincia"),
                    "estado": res.get("estado") or "ACTIVO",
                    "fuente": self.FUENTE,
                    "datos_extra": {"tipo_contribuyente": "SOCIEDAD", "fuente_web": "DuckDuckGo Search"}
                })
            return enriquecidos
            
        else:
            # Búsqueda usando FTS5 en la base local (modo MOCK/local)
            query = self._limpiar_para_busqueda(razon_social)
            if not query or len(query) < 3:
                return []
                
            # Ejecutar búsqueda local
            # No filtramos por fuente (fuente=None) para SRI fallback total
            resultados_db = self.searcher.search_by_name(
                query, 
                provincia=provincia,
                limit=5
            )
            
            # Enriquecer resultados con metadatos específicos de SRI
            candidatos = []
            for res in resultados_db:
                candidatos.append({
                    "ruc": res["ruc"],
                    "razon_social": res["razon_social"],
                    "provincia": res["provincia"],
                    "estado": res["estado"],
                    "fuente": self.FUENTE,
                    "datos_extra": {"tipo_contribuyente": res["datos_extra"]["tipo_interno"]}
                })
                
            return candidatos
    
    def _limpiar_para_busqueda(self, texto: str) -> str:
        """Limpia ruido excesivo para mejorar match en FTS."""
        texto = texto.upper().strip()
        # Quitar basura común y puntos/comas
        texto = re.sub(r'[^A-Z0-9\s]', ' ', texto)
        # Quitar palabras de ruido (opcional ya que FTS lo maneja bien,
        # pero ayuda a acortar la query)
        ruido = {"DE", "DEL", "LA", "EL", "Y", "LTDA", "SA", "CIA", "CA", "S.A."}
        parts = [p for p in texto.split() if p not in ruido and len(p) > 1]
        return " ".join(parts)
    
    def close(self):
        if hasattr(self, 'searcher'):
            self.searcher.close()


