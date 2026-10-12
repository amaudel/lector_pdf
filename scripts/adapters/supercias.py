from .base import BaseAdapter

class SuperciasAdapter(BaseAdapter):
    """
    Adapter para consultar Compañias de Responsabilidad Limitada, Anónimas, etc.
    (Compañías sujetas al ente de control Superintendencia de Compañías)
    """
    def search(self, name_query, province_query=None):
        return {
            "ruc_final": None,
            "estado_resolucion": "SIN_RESULTADO_EXTERNO",
            "fuente_consultada": "SUPERCIA_STUB",
            "coincidencia_nombre": "N/A",
            "coincidencia_provincia": "N/A",
            "observaciones": "Endpoint/Dataset de Supercias pendiente."
        }
