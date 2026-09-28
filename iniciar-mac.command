#!/bin/sh
# Doble clic en este archivo para abrir el programa (Mac). También sirve en Linux.
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
    echo ""
    echo "Preparando el programa por primera vez. Puede tardar un par de minutos..."
    echo ""
    if ! python3 -c "import sys; assert sys.version_info >= (3, 10)" >/dev/null 2>&1; then
        echo "No se ha encontrado Python 3.10 o superior en este ordenador."
        echo ""
        echo "1. Entra en https://www.python.org/downloads/ y pulsa 'Download Python'."
        echo "2. Instálalo como cualquier otro programa."
        echo "3. Vuelve a hacer doble clic en este archivo."
        open https://www.python.org/downloads/ 2>/dev/null
        read -p "Pulsa Intro para cerrar..." _
        exit 1
    fi
    if ! python3 -m venv .venv || ! .venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt; then
        rm -rf .venv
        echo "Algo ha fallado. Comprueba la conexión a internet (solo se necesita la primera vez) y vuelve a intentarlo."
        read -p "Pulsa Intro para cerrar..." _
        exit 1
    fi
fi

.venv/bin/python actualizar.py

echo ""
echo "============================================================"
echo " El programa se está abriendo en el navegador."
echo " NO CIERRES ESTA VENTANA mientras lo uses."
echo "============================================================"
.venv/bin/python iniciar.py
