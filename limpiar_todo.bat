@echo off
title Limpieza del Lector PDF
echo ==================================================
echo   LIMPIANDO TODAS LAS CARPETAS (BORRANDO HISTORIAL)
echo ==================================================
echo.
echo [*] Eliminando ZIPs antiguos, archivos temporales y Excels viejos...

powershell -Command "Remove-Item -Path 'data\input\*.zip' -Force -ErrorAction SilentlyContinue"
powershell -Command "Remove-Item -Path 'data\temp\*' -Recurse -Force -Exclude '.keep' -ErrorAction SilentlyContinue"
powershell -Command "Remove-Item -Path 'data\output\*' -Recurse -Force -Exclude '.keep' -ErrorAction SilentlyContinue"
powershell -Command "Remove-Item -Path 'data\master\*.sqlite' -Force -ErrorAction SilentlyContinue"

echo.
echo [*] ¡Todo el sistema ha quedado impecable y listo desde cero!
echo ==================================================
pause
