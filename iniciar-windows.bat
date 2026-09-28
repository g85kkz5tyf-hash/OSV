@echo off
chcp 65001 >nul
title Gestion Optica
cd /d "%~dp0"

if exist .venv\Scripts\python.exe goto arrancar

echo.
echo  Preparando el programa por primera vez. Puede tardar un par de minutos...
echo.
set PY=
py -3 --version >nul 2>&1 && set PY=py -3
if not defined PY (python --version >nul 2>&1 && set PY=python)
if not defined PY goto sin_python

%PY% -m venv .venv || goto error
.venv\Scripts\python -m pip install --disable-pip-version-check -q -r requirements.txt || goto error
echo  Listo.

:arrancar
echo.
echo  ============================================================
echo   El programa se esta abriendo en el navegador.
echo   NO CIERRES ESTA VENTANA mientras lo uses.
echo   Para salir, cierra esta ventana.
echo  ============================================================
echo.
.venv\Scripts\python iniciar.py
pause
exit /b

:sin_python
echo.
echo  No se ha encontrado Python en este ordenador.
echo.
echo  1. Entra en https://www.python.org/downloads/ y pulsa "Download Python".
echo  2. Al instalar, MARCA la casilla "Add python.exe to PATH".
echo  3. Vuelve a hacer doble clic en este archivo.
echo.
start https://www.python.org/downloads/
pause
exit /b

:error
echo.
echo  Algo ha fallado al preparar el programa. Comprueba que hay conexion
echo  a internet (solo se necesita la primera vez) y vuelve a intentarlo.
if exist .venv rmdir /s /q .venv
pause
