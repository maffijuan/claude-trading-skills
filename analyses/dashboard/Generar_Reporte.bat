@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0..\.."
echo ==================================================
echo    Generador de Reporte Fundamental (HTML)
echo ==================================================
echo.
echo  Universos preset:  dow30  ^|  megacap_tech  ^|  staples
echo  ...o escribi tickers separados por coma (AAPL,MSFT,PEP)
echo.
set "TK="
set /p TK="Universo o tickers [enter = dow30]: "
if "%TK%"=="" set "TK=dow30"

set "METHOD="
set /p METHOD="Periodo parcial [enter = ttm] (runrate/ttm/none): "
if "%METHOD%"=="" set "METHOD=ttm"

echo.
echo Generando reporte... (puede tardar segun la cantidad de tickers)
echo.

REM elegir python o el launcher py
set "PY=python"
where python >nul 2>nul || set "PY=py"

if /I "%TK%"=="dow30"        ( "%PY%" analyses\dashboard\build_static.py --universe dow30 --method %METHOD% & goto done )
if /I "%TK%"=="megacap_tech" ( "%PY%" analyses\dashboard\build_static.py --universe megacap_tech --method %METHOD% & goto done )
if /I "%TK%"=="staples"      ( "%PY%" analyses\dashboard\build_static.py --universe staples --method %METHOD% & goto done )
"%PY%" analyses\dashboard\build_static.py %TK:,= % --method %METHOD%

:done
echo.
echo Listo. Abriendo la carpeta de reportes...
start "" "analyses\reports"
echo.
pause
