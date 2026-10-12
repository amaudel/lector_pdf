from .dataset import DatasetAdapter
from .seps import SepsAdapter
from .supercias import SuperciasAdapter

class SourceRouter:
    """
    Router Inteligente de Fuentes (Fase 3).
    Inspecciona la ontología detectada previamente en la Fase 2 y decide a qué API/Catálogo
    estructurado consultarle la validación de un RUC sin malgastar recursos de red.
    """
    def __init__(self):
        self.dataset = DatasetAdapter()
        self.seps = SepsAdapter()
        self.supercias = SuperciasAdapter()

    def route_for_completion(self, candidate_data):
        """
        Enruta resoluciones exclusivas para los candidatos que pasaron
        los filtros heurísticos y buscan que el sistema deduzca y emita un RUC final en Ruta B.
        """
        tipo = candidate_data.get("tipo_entidad_detectada", "")
        tipo_str = tipo.upper() if tipo else ""
        nombre = candidate_data.get("razon_social_normalizada", "")
        prov = candidate_data.get("provincia_mencionada", "")
        
        # 1. Filtro Prioritario de Sector Cooperativo / Popular Solidario
        if "COOPERATIVA" in tipo_str or "EPS" in tipo_str:
            res = self.seps.search(nombre, prov)
            if res["estado_resolucion"] != "SIN_RESULTADO_EXTERNO":
                return res
        
        # 2. Filtro Prioritario Sociedades Comerciales
        elif "COMPAÑIA" in tipo_str or "EMPRESA" in tipo_str:
            res = self.supercias.search(nombre, prov)
            if res["estado_resolucion"] != "SIN_RESULTADO_EXTERNO":
                return res
                
        # 3. Fallback Universal (Dataset SQL Consolidado / RUC Nacional Offline)
        res_fallback = self.dataset.search(nombre, prov)
        return res_fallback
