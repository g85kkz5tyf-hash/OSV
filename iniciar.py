"""Arranca el programa de gestión de la óptica y lo abre en el navegador."""
import logging
import socket
import threading
import time
import urllib.request
import webbrowser

import flask.cli

from optica import create_app
from optica.main import MARCA_ESTADO

# Puertos poco habituales: el 5000 lo usa AirPlay en los Mac y daba página en blanco.
PUERTOS = range(8765, 8776)

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
            print("El programa ya está abierto. Abriendo el navegador...")
            print("Si no se abre, escribe en el navegador:", url)
            webbrowser.open(url)
            return
        if libre(puerto):
            break
    else:
        print("No se ha encontrado un puerto libre. Reinicia el ordenador y vuelve a intentarlo.")
        return

    print()
    print("  Gestión Óptica en marcha.")
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
