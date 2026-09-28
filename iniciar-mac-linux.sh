#!/bin/sh
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
    echo "Preparando el programa por primera vez..."
    python3 -m venv .venv
    .venv/bin/python -m pip install -r requirements.txt
fi
.venv/bin/python iniciar.py
