"""
Utilidad: Empaqueta todos los PDFs sueltos de data/input en un ZIP temporal
llamado 'pdfs_sueltos.zip' para que el orquestador pueda procesarlos igual
que un lote normal.
"""
import sys
import zipfile
from pathlib import Path

def empaquetar_pdfs_sueltos(input_dir_str):
    input_dir = Path(input_dir_str).resolve()
    
    # Buscar solo PDFs sueltos (no dentro de subcarpetas)
    pdfs = [f for f in input_dir.glob("*.pdf") if f.is_file()]
    
    if not pdfs:
        print("[*] No hay PDFs sueltos en la carpeta de entrada. Nada que empaquetar.")
        sys.exit(0)
    
    zip_destino = input_dir / "pdfs_sueltos.zip"
    
    print(f"[*] Se encontraron {len(pdfs)} PDF(s) suelto(s). Empaquetando en: {zip_destino.name}")
    
    with zipfile.ZipFile(zip_destino, 'w', zipfile.ZIP_DEFLATED) as zf:
        for pdf in pdfs:
            zf.write(pdf, arcname=pdf.name)
            print(f"   + Añadido: {pdf.name}")
    
    print(f"[OK] ZIP temporal creado exitosamente: {zip_destino}")

if __name__ == "__main__":
    carpeta = sys.argv[1] if len(sys.argv) > 1 else "data/input"
    empaquetar_pdfs_sueltos(carpeta)
