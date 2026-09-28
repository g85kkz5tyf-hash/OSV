"""Arranca el programa de gestión de la óptica y lo abre en el navegador."""
import logging
import secrets
import socket
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

import flask.cli

from optica import create_app
from optica.main import MARCA_ESTADO

# Puertos poco habituales: el 5000 lo usa AirPlay en los Mac y daba página en blanco.
PUERTOS = range(8765, 8776)
# Clave para que un arranque nuevo pueda cerrar la copia que ya estaba abierta
ARCHIVO_CLAVE = Path(__file__).resolve().parent / "datos" / ".instancia"

app = create_app()


def es_nuestro(puerto):
    """True si en ese puerto responde este mismo programa (ya abierto)."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{puerto}/estado", timeout=2) as r:
            return r.read().decode() == MARCA_ESTADO
    except Exception:
        return False


def libre(puerto):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", puerto))
            return True
        except OSError:
            return False


def cerrar_anterior(puerto):
    """Pide a la copia ya abierta que se cierre, para usar la versión recién instalada."""
    try:
        clave = ARCHIVO_CLAVE.read_text(encoding="utf-8").strip()
        datos = urllib.parse.urlencode({"clave": clave}).encode()
        urllib.request.urlopen(f"http://127.0.0.1:{puerto}/cerrar", data=datos, timeout=3).read()
    except Exception:
        return False
    for _ in range(20):
        if libre(puerto):
            return True
        time.sleep(0.25)
    return False


def abrir_cuando_este_listo(url, puerto):
    """Abre el navegador solo cuando el programa ya responde, para no ver una página vacía."""
    for _ in range(120):
        if es_nuestro(puerto):
            webbrowser.open(url)
            return
        time.sleep(0.5)
    print("El programa tarda en arrancar. Abre el navegador y escribe:", url)


def main():
    for puerto in PUERTOS:
        url = f"http://127.0.0.1:{puerto}"
        if es_nuestro(puerto):
            if cerrar_anterior(puerto):
                break
            # Una versión antigua que no sabe cerrarse sola
            print("El programa ya estaba abierto en otra ventana negra.")
            print("Para usar la versión actualizada, cierra TODAS las ventanas negras")
            print("y vuelve a abrir el programa. Mientras tanto se abre el que ya estaba.")
            webbrowser.open(url)
            return
        if libre(puerto):
            break
    else:
        print("No se ha encontrado un puerto libre. Reinicia el ordenador y vuelve a intentarlo.")
        return

    clave = secrets.token_hex(16)
    app.config["CLAVE_CIERRE"] = clave
    try:
        ARCHIVO_CLAVE.parent.mkdir(exist_ok=True)
        ARCHIVO_CLAVE.write_text(clave, encoding="utf-8")
    except OSError:
        pass

    print()
    print("  Gestión Óptica en marcha.")
    if app.config["VERSION"]:
        print("  Versión del", app.config["VERSION"])
    print("  Si el navegador no se abre solo, escribe esta dirección:", url)
    print("  Deja esta ventana abierta mientras uses el programa. Ciérrala para salir.")
    print()
    # Ocultar mensajes técnicos del servidor
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    flask.cli.show_server_banner = lambda *args, **kwargs: None
    threading.Thread(target=abrir_cuando_este_listo, args=(url, puerto), daemon=True).start()
    app.run(host="127.0.0.1", port=puerto)


if __name__ == "__main__":
    main()
