from .base import BaseAdapter

class MockAdapter(BaseAdapter):
    """
    Simulador que actúa como Interface Dummy para peticiones de red externas.
    Respeta la arquitectura pero no inventa validaciones.
    """
    def search(self, name_query, province_query=None):
        # Simulación de falla externa general por no tener conexión real instalada aún.
        return {
            "ruc_final": None,
            "estado_resolucion": "SIN_RESULTADO_EXTERNO",
            "fuente_consultada": "MOCK_SEARCH_API",
            "coincidencia_nombre": "N/A",
            "coincidencia_provincia": "N/A",
            "observaciones": "Búsqueda mockeada. Adaptador real (SRI/Supercias) pendiente de conexión."
        }
