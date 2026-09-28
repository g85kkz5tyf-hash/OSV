@echo off
cd /d "%~dp0"
if not exist .venv (
    echo Preparando el programa por primera vez...
    py -3 -m venv .venv || python -m venv .venv
    .venv\Scripts\python -m pip install -r requirements.txt
)
.venv\Scripts\python iniciar.py
pause
