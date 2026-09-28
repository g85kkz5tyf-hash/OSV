"""Arranca el programa de gestión de la óptica y lo abre en el navegador."""
import threading
import webbrowser

from optica import create_app

PUERTO = 5000

app = create_app()

if __name__ == "__main__":
    url = f"http://127.0.0.1:{PUERTO}"
    print(f"Gestión Óptica en marcha: {url}")
    print("Deja esta ventana abierta mientras uses el programa. Ciérrala para salir.")
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=PUERTO)
