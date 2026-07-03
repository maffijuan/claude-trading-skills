@echo off
REM Doble-click para abrir el dashboard interactivo (server local + navegador).
REM Solo para uso propio: analiza cualquier ticker en vivo. Requiere Python + Flask.
cd /d "%~dp0..\.."
set "PY=python"
where python >nul 2>nul || set "PY=py"
echo Iniciando el dashboard en http://127.0.0.1:5000  (cerra esta ventana para detenerlo)
"%PY%" analyses\dashboard\app.py --open
pause
