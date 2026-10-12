class BaseAdapter:
    def search(self, name_query, province_query=None):
        """
        Debe devolver un diccionario con:
        - ruc_final: string o None
        - estado_resolucion: string (e.g. SIN_RESULTADO_EXTERNO, VALIDADO_EXTERNAMENTE)
        - fuente_consultada: string
        - coincidencia_nombre: string (ALTA, MEDIA, BAJA, N/A)
        - coincidencia_provincia: string (ALTA, MEDIA, BAJA, N/A)
        - observaciones: string
        """
        raise NotImplementedError("El adapter debe implementar el método search()")
