"""
Adapter REAL para SEPS (Superintendencia de Economía Popular y Solidaria).
Consulta el catálogo de cooperativas y asociaciones descargado en modo MOCK/local, o realiza una búsqueda web real en modo REAL.
"""
from .web_base import WebAdapter
from .db_search_base import LocalDBSearcher
import re

class SepsWebAdapter(WebAdapter):
    """
    Adapter SEPS para enriquecimiento.
    En modo REAL realiza búsquedas en DuckDuckGo + extracción con GPT-4o-mini.
    En modo MOCK realiza búsquedas locales en la base SQLite.
    """
    
    FUENTE = "SEPS"
    
    def __init__(self, modo: str = "REAL"):
        super().__init__(modo)
        self.searcher = LocalDBSearcher()

    def search(self, razon_social: str, provincia: str = None,
               tipo_entidad: str = None) -> list:
        """Busca cooperativas y asociaciones en la web o en la base REAL."""
        if self.modo == "REAL":
            query = f"RUC cooperativa {razon_social} Ecuador"
            candidatos = self._search_web_and_extract(query, razon_social)
            
            enriquecidos = []
            for res in candidatos:
                enriquecidos.append({
                    "ruc": res["ruc"],
                    "razon_social": res["razon_social"],
                    "provincia": res.get("provincia"),
                    "estado": res.get("estado") or "ACTIVO",
                    "fuente": self.FUENTE,
                    "datos_extra": {"tipo_organizacion": "COOPERATIVA", "fuente_web": "Web Search"}
                })
            return enriquecidos
            
        else:
            query = self._limpiar_para_busqueda(razon_social)
            if not query or len(query) < 3:
                return []
                
            candidatos = []
            for src in ["SEPS_FIN", "SEPS_EPS"]:
                resultados_db = self.searcher.search_by_name(
                    query, 
                    fuente=src,
                    provincia=provincia,
                    limit=5
                )
                for res in resultados_db:
                    candidatos.append({
                        "ruc": res["ruc"],
                        "razon_social": res["razon_social"],
                        "provincia": res["provincia"],
                        "estado": res["estado"],
                        "fuente": self.FUENTE,
                        "datos_extra": {
                            "tipo_organizacion": "COOPERATIVA" if src == "SEPS_FIN" else "ASOCIACION",
                            "fuente_detalle": src
                        }
                    })
            
            return candidatos[:5]
    
    def _limpiar_para_busqueda(self, texto: str) -> str:
        """Limpia ruido excesivo para mejorar match."""
        texto = texto.upper().strip()
        texto = re.sub(r'[^A-Z0-9\s]', ' ', texto)
        # Conservar palabras clave pero no ruidosas
        ruido = {"DE", "DEL", "LA", "EL", "Y", "LTDA", "SA", "CIA", "CA", "S.A."}
        parts = [p for p in texto.split() if p not in ruido and len(p) > 1]
        return " ".join(parts)
        
    def close(self):
        if hasattr(self, 'searcher'):
            self.searcher.close()


