@echo off
title LECTOR PDF - Interfaz Web
echo =======================================================
echo   LECTOR PDF - Iniciando Interfaz Frontend Web Amigable
echo =======================================================
echo.

echo [*] Liberando puerto 8000 (por si hay instancias previas activas)...
powershell -Command "Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"

echo [*] Abriendo el navegador en http://localhost:8000...
start "" "http://localhost:8000"
echo [*] Iniciando servidor local en FastAPI...
echo     (Presiona Ctrl+C para detener el servidor)
echo.

python web_server.py
if %ERRORLEVEL% neq 0 (
    echo.
    echo =======================================================
    echo [ERROR] El servidor finalizo con un error (Codigo: %ERRORLEVEL%).
    echo.
    echo Posibles causas:
    echo 1. Python no esta en las variables de entorno (PATH).
    echo 2. Faltan librerias en el entorno virtual activo.
    echo =======================================================
    echo.
    pause
)
