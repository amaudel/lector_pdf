@echo off
echo ==================================================
echo   INICIANDO PROCESAMIENTO MULTIPLE DE ARCHIVOS
echo   (ZIPs + PDFs sueltos)
echo ==================================================
echo.

REM --- PASO PREVIO: Si hay PDFs sueltos en data\input, empaquetarlos en un ZIP ---
echo [*] Verificando si hay PDFs sueltos en la carpeta de entrada...
python scripts\crear_zip_desde_pdfs.py "data\input"
echo.

REM --- Recorrer todos los archivos ZIP dentro de la carpeta data\input ---
set HUBO_ARCHIVOS=0

for %%f in (data\input\*.zip) do (
    set HUBO_ARCHIVOS=1
    echo ==================================================
    echo [*] Iniciando turno para el archivo: %%~nxf
    echo ==================================================
    
    python scripts\process_batch.py --zip_path "%%f" --master_db "data\master\master_entities.sqlite" --output_dir "data\output"
    
    echo.
    echo [*] Terminado con exito: %%~nxf
    echo ==================================================
    echo.
)

if %HUBO_ARCHIVOS%==0 (
    echo [!] No se encontraron archivos ZIP ni PDFs para procesar en data\input\
    echo     Por favor, coloca tus archivos .zip o .pdf en esa carpeta.
)

REM --- Limpiar el ZIP temporal de PDFs sueltos si fue creado ---
if exist "data\input\pdfs_sueltos.zip" (
    echo [*] Limpiando ZIP temporal de PDFs sueltos...
    del "data\input\pdfs_sueltos.zip"
)

echo.
echo ==================================================
echo   TODOS LOS ARCHIVOS HAN SIDO PROCESADOS EXITOSAMENTE
echo ==================================================
pause
