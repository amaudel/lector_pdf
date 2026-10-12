"""Genera SQL para llevar tus datos locales a la D1 de Cloudflare.

  python migrar_datos.py                 -> migracion/maestro.sql   (master_entities, master_evidence, processed_batches)
  python migrar_datos.py --catalogo-seps -> migracion/catalogo_seps.sql (~21 mil filas SEPS; cabe en el plan gratuito de D1)

Luego, con `wrangler login` hecho:
  npx wrangler d1 execute lector-pdf-db --remote --file migracion/maestro.sql
El catálogo SRI (3.7 millones de filas) NO se genera aquí: supera los límites del plan gratuito de D1.
"""
import argparse
import sqlite3
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SALIDA = Path(__file__).resolve().parent / "migracion"


def lit(v):
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def arreglar(s):
    """Corrige la doble codificación latin-1/utf-8 que tiene el catálogo local (igual que hacía dataset.py)."""
    if not s:
        return s
    try:
        return s.encode("latin-1").decode("utf-8")
    except Exception:
        return s


def volcar(con, tabla, columnas, f, filtro=None, transformar=None, trozo=80, ignorar=True):
    filas = con.execute(f"SELECT {', '.join(columnas)} FROM {tabla}" + (f" WHERE {filtro}" if filtro else "")).fetchall()
    for i in range(0, len(filas), trozo):
        valores = []
        for r in filas[i:i + trozo]:
            r = transformar(list(r)) if transformar else list(r)
            valores.append("(" + ",".join(lit(x) for x in r) + ")")
        f.write(f"INSERT {'OR IGNORE ' if ignorar else ''}INTO {tabla} ({', '.join(columnas)}) VALUES\n" + ",\n".join(valores) + ";\n")
    return len(filas)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalogo-seps", action="store_true")
    a = ap.parse_args()
    SALIDA.mkdir(exist_ok=True)

    if not a.catalogo_seps:
        con = sqlite3.connect(BASE / "data" / "master" / "master_entities.sqlite")
        ruta = SALIDA / "maestro.sql"
        with open(ruta, "w", encoding="utf-8") as f:
            n1 = volcar(con, "master_entities", ["ruc", "razon_social_canonica", "razon_social_normalizada", "tipo_entidad", "provincia_preferida",
                        "estado_resolucion_master", "fuente_primaria", "fecha_primera_aparicion", "fecha_ultima_actualizacion", "total_lotes_detectado", "total_menciones"], f)
            n2 = volcar(con, "master_evidence", ["ruc", "lote", "archivo_origen", "pagina_pdf", "fragmento_evidencia", "estado_resolucion_origen", "fecha_ingesta", "fuente_ruc"], f)
            n3 = volcar(con, "processed_batches", ["lote_base", "fecha_procesamiento", "total_registros_leidos", "total_insertados", "total_actualizados", "referencia_archivo"], f, ignorar=False)
        print(f"{ruta}: {n1} entidades, {n2} evidencias, {n3} lotes ya procesados")
    else:
        con = sqlite3.connect(BASE / "data" / "external" / "catalogs.sqlite")
        ruta = SALIDA / "catalogo_seps.sql"
        with open(ruta, "w", encoding="utf-8") as f:
            n = volcar(con, "entities", ["ruc", "razon_social", "provincia", "tipo", "fuente"], f, filtro="fuente LIKE 'SEPS%'",
                       transformar=lambda r: [r[0], arreglar(r[1]), arreglar(r[2]), r[3], r[4]], trozo=150, ignorar=False)
            f.write("INSERT INTO catalogo_fts(catalogo_fts) VALUES('rebuild');\n")
        print(f"{ruta}: {n} filas SEPS")


if __name__ == "__main__":
    main()
