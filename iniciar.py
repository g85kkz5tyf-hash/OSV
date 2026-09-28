"""Arranca el programa de gestión de la óptica y lo abre en el navegador."""
import logging
import socket
import threading
import webbrowser

import flask.cli

from optica import create_app

PUERTO = 5000

app = create_app()


def puerto_ocupado():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", PUERTO)) == 0


if __name__ == "__main__":
    url = f"http://127.0.0.1:{PUERTO}"
    if puerto_ocupado():
        # El programa ya estaba abierto: solo mostramos el navegador
        print("El programa ya está abierto. Abriendo el navegador...")
        webbrowser.open(url)
    else:
        print(f"Gestión Óptica en marcha: {url}")
        print("Deja esta ventana abierta mientras uses el programa. Ciérrala para salir.")
        # Ocultar mensajes técnicos del servidor
        logging.getLogger("werkzeug").setLevel(logging.ERROR)
        flask.cli.show_server_banner = lambda *args, **kwargs: None
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
        app.run(host="127.0.0.1", port=PUERTO)
