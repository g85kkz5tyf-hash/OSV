"""Busca en GitHub una versión nueva del programa y la instala.

Se ejecuta al abrir el programa. Nunca toca la carpeta «datos» (clientes, ventas, stock),
y antes de actualizar guarda una copia de la base de datos en «datos/copias».
Si no hay internet o algo falla, se sigue usando la versión actual.
"""
import io
import json
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

REPOSITORIO = "g85kkz5tyf-hash/OSV"
RAMA = "claude/optica-management-software-cnvykq"

RAIZ = Path(__file__).resolve().parent
ARCHIVO_VERSION = RAIZ / "version.txt"
# Lo que se reemplaza al actualizar. Los lanzadores (.bat / .command) no se tocan
# porque están en uso mientras se actualiza.
CARPETAS = ["optica"]
ARCHIVOS = ["iniciar.py", "actualizar.py", "requirements.txt", "LEEME-INSTALACION.txt", "README.md"]
COPIAS_A_CONSERVAR = 10


def certificados():
    """Certificados de seguridad para HTTPS.

    El Python que se instala en los Mac no trae certificados y no puede conectarse a
    GitHub; en ese caso se usan los que incluye pip (siempre presente en el programa).
    """
    try:
        from pip._vendor import certifi
    except ImportError:
        try:
            import certifi
        except ImportError:
            return None
    return ssl.create_default_context(cafile=certifi.where())


def descargar(url, timeout=10):
    peticion = urllib.request.Request(url, headers={"User-Agent": "gestion-optica"})
    try:
        with urllib.request.urlopen(peticion, timeout=timeout) as r:
            return r.read()
    except urllib.error.URLError as e:
        contexto = certificados()
        if not isinstance(e.reason, ssl.SSLError) or contexto is None:
            raise
        with urllib.request.urlopen(peticion, timeout=timeout, context=contexto) as r:
            return r.read()


def version_local():
    try:
        return ARCHIVO_VERSION.read_text(encoding="utf-8").split()[0]
    except (OSError, IndexError):
        return ""


def version_remota():
    datos = json.loads(descargar(f"https://api.github.com/repos/{REPOSITORIO}/commits/{RAMA}"))
    fecha = datos["commit"]["committer"]["date"][:10]
    return datos["sha"], fecha


def copia_de_seguridad():
    bd = RAIZ / "datos" / "optica.db"
    if not bd.exists():
        return
    copias = RAIZ / "datos" / "copias"
    copias.mkdir(exist_ok=True)
    destino = copias / f"antes-de-actualizar-{datetime.now():%Y-%m-%d-%H%M%S}.db"
    import sqlite3
    origen, copia = sqlite3.connect(bd), sqlite3.connect(destino)
    with copia:
        origen.backup(copia)
    origen.close()
    copia.close()
    for vieja in sorted(copias.glob("antes-de-actualizar-*.db"))[:-COPIAS_A_CONSERVAR]:
        vieja.unlink()


def instalar(sha):
    contenido = descargar(f"https://codeload.github.com/{REPOSITORIO}/zip/{sha}", timeout=60)
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(io.BytesIO(contenido)) as z:
            z.extractall(tmp)
        nueva = next(Path(tmp).iterdir())  # carpeta «OSV-<sha>»
        if not (nueva / "optica" / "__init__.py").exists():
            raise RuntimeError("la descarga no contiene el programa")

        requisitos_antes = (RAIZ / "requirements.txt").read_bytes() if (RAIZ / "requirements.txt").exists() else b""
        copia_de_seguridad()
        for carpeta in CARPETAS:
            actual, anterior = RAIZ / carpeta, RAIZ / f"{carpeta}.anterior"
            shutil.rmtree(anterior, ignore_errors=True)
            if actual.exists():
                actual.rename(anterior)
            try:
                shutil.copytree(nueva / carpeta, actual)
            except Exception:
                # Dejar el programa como estaba
                shutil.rmtree(actual, ignore_errors=True)
                if anterior.exists():
                    anterior.rename(actual)
                raise
            shutil.rmtree(anterior, ignore_errors=True)
        for archivo in ARCHIVOS:
            if (nueva / archivo).exists():
                shutil.copy2(nueva / archivo, RAIZ / archivo)

    if (RAIZ / "requirements.txt").read_bytes() != requisitos_antes:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-q",
             "-r", str(RAIZ / "requirements.txt")],
            check=True,
        )


def main():
    print("Buscando actualizaciones...")
    try:
        sha, fecha = version_remota()
    except Exception as e:
        print("No se ha podido comprobar si hay actualizaciones. Se usa la versión actual.")
        print(f"  (Motivo: {e})")
        return
    if sha == version_local():
        print("El programa está al día.")
        return
    print("Hay una versión nueva. Actualizando, espera un momento...")
    try:
        instalar(sha)
    except Exception as e:
        print(f"No se ha podido actualizar ({e}). Se usa la versión actual.")
        return
    ARCHIVO_VERSION.write_text(f"{sha} {fecha}\n", encoding="utf-8")
    print(f"Programa actualizado (versión del {fecha[8:10]}/{fecha[5:7]}/{fecha[:4]}).")


if __name__ == "__main__":
    main()
