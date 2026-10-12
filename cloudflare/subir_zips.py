"""Sube a Cloudflare los ZIP de data/input que aún no estén allá, usando la API del Worker.

  set LECTOR_URL=https://lector-pdf-agente.<tu-subdominio>.workers.dev
  set LECTOR_TOKEN=<el mismo API_TOKEN que definiste como secret>
  python subir_zips.py                 # sube todos los ZIP que falten (sin procesarlos)
  python subir_zips.py --procesar      # además lanza el procesamiento de cada uno
  python subir_zips.py --solo-nuevos 5 # sube/procesa como máximo 5 por corrida

Los ZIP ya subidos se omiten (compara por nombre y tamaño), así que puedes agregar lotes nuevos a data/input
y volver a correrlo cuando quieras.
"""
import argparse
import os
import sys
from pathlib import Path
from urllib.parse import quote

import requests

ENTRADA = Path(__file__).resolve().parent.parent / "data" / "input"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--procesar", action="store_true")
    ap.add_argument("--investigar", action="store_true", help="con --procesar: investigar en internet lo que quede sin RUC")
    ap.add_argument("--limite", type=int, default=5, help="entidades a investigar por lote")
    ap.add_argument("--solo-nuevos", type=int, default=0, help="máximo de ZIP por corrida (0 = todos)")
    a = ap.parse_args()
    url, token = os.environ.get("LECTOR_URL", "").rstrip("/"), os.environ.get("LECTOR_TOKEN", "")
    if not url or not token:
        sys.exit("Define LECTOR_URL y LECTOR_TOKEN (ver docstring).")
    h = {"Authorization": f"Bearer {token}"}
    remotos = {z["nombre"]: z["bytes"] for z in requests.get(f"{url}/api/zips", headers=h, timeout=60).json()}
    pendientes = [p for p in sorted(ENTRADA.glob("*.zip")) if remotos.get(p.name) != p.stat().st_size]
    if a.solo_nuevos:
        pendientes = pendientes[: a.solo_nuevos]
    print(f"{len(pendientes)} ZIP por subir ({len(remotos)} ya estaban en Cloudflare)")
    for p in pendientes:
        q = f"?procesar={int(a.procesar)}&investigar={int(a.investigar)}&limite={a.limite}"
        with open(p, "rb") as f:
            r = requests.put(f"{url}/api/zips/{quote(p.name)}{q}", headers=h, data=f, timeout=300)
        print(("OK  " if r.ok else f"ERR {r.status_code} ") + p.name, r.text[:80] if not r.ok else "")


if __name__ == "__main__":
    main()
