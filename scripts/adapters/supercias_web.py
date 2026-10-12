"""
Adapter REAL para Supercias (Superintendencia de Compañías).
En ausencia de catálogo propio, consulta el catálogo SRI general local en modo MOCK/local, o realiza una búsqueda web real en modo REAL.
"""
from .web_base import WebAdapter
from .db_search_base import LocalDBSearcher
import re

class SuperciasWebAdapter(WebAdapter):
    """
    Adapter Supercias para enriquecimiento.
    En modo REAL realiza búsquedas en DuckDuckGo + extracción con GPT-4o-mini.
    En modo MOCK realiza búsquedas locales en la base SQLite.
    """
    
    FUENTE = "SUPERCIAS"
    
    def __init__(self, modo: str = "REAL"):
        super().__init__(modo)
        self.searcher = LocalDBSearcher()

    def search(self, razon_social: str, provincia: str = None,
               tipo_entidad: str = None) -> list:
        """Busca compañías mercantiles en la web o en la base REAL."""
        if self.modo == "REAL":
            query = f"RUC compañia {razon_social} Ecuador"
            candidatos = self._search_web_and_extract(query, razon_social)
            
            enriquecidos = []
            for res in candidatos:
                enriquecidos.append({
                    "ruc": res["ruc"],
                    "razon_social": res["razon_social"],
                    "provincia": res.get("provincia"),
                    "estado": res.get("estado") or "ACTIVO",
                    "fuente": self.FUENTE,
                    "datos_extra": {"tipo_sociedad": "MERCANTIL", "fuente_web": "Web Search"}
                })
            return enriquecidos
            
        else:
            query = self._limpiar_para_busqueda(razon_social)
            if not query or len(query) < 3:
                return []
                
            # Ejecutar búsqueda local en SRI (que incluye compañías)
            resultados_db = self.searcher.search_by_name(
                query, 
                fuente="SRI",
                provincia=provincia,
                limit=5
            )
            
            candidatos = []
            for res in resultados_db:
                candidatos.append({
                    "ruc": res["ruc"],
                    "razon_social": res["razon_social"],
                    "provincia": res["provincia"],
                    "estado": res["estado"],
                    "fuente": self.FUENTE,
                    "datos_extra": {"tipo_sociedad": "MERCANTIL", "fuente_real": "SRI_CAT"}
                })
                
            return candidatos
    
    def _limpiar_para_busqueda(self, texto: str) -> str:
        """Limpia ruido excesivo."""
        texto = texto.upper().strip()
        texto = re.sub(r'[^A-Z0-9\s]', ' ', texto)
        ruido = {"DE", "DEL", "LA", "EL", "Y", "LTDA", "SA", "CIA", "CA", "S.A."}
        parts = [p for p in texto.split() if p not in ruido and len(p) > 1]
        return " ".join(parts)
        
    def close(self):
        if hasattr(self, 'searcher'):
            self.searcher.close()


