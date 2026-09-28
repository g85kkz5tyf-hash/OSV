import io
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

import actualizar

RAIZ_REPO = Path(__file__).resolve().parent.parent


def zip_del_programa(texto_extra=""):
    """Simula el ZIP que devuelve GitHub con la versión nueva del programa."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        for ruta in [*RAIZ_REPO.joinpath("optica").rglob("*"), *(RAIZ_REPO / a for a in actualizar.ARCHIVOS)]:
            if ruta.is_file() and "__pycache__" not in ruta.parts:
                datos = ruta.read_bytes()
                if ruta.name == "iniciar.py":
                    datos += texto_extra.encode()
                z.writestr(f"OSV-abc123/{ruta.relative_to(RAIZ_REPO).as_posix()}", datos)
    return buffer.getvalue()


@pytest.fixture
def instalacion(tmp_path, monkeypatch):
    """Una instalación antigua con datos del cliente."""
    (tmp_path / "optica").mkdir()
    (tmp_path / "optica" / "viejo.py").write_text("# versión antigua")
    (tmp_path / "iniciar-windows.bat").write_text("lanzador")
    (tmp_path / "requirements.txt").write_text((RAIZ_REPO / "requirements.txt").read_text())
    (tmp_path / "datos").mkdir()
    conn = sqlite3.connect(tmp_path / "datos" / "optica.db")
    conn.execute("CREATE TABLE clientes (nombre TEXT)")
    conn.execute("INSERT INTO clientes VALUES ('Ana')")
    conn.commit()
    conn.close()
    monkeypatch.setattr(actualizar, "RAIZ", tmp_path)
    monkeypatch.setattr(actualizar, "ARCHIVO_VERSION", tmp_path / "version.txt")
    return tmp_path


def github_falso(monkeypatch, sha="abc123", zip_bytes=None):
    def descargar(url, timeout=10):
        if "api.github.com" in url:
            return json.dumps({"sha": sha, "commit": {"committer": {"date": "2026-09-30T10:00:00Z"}}}).encode()
        return zip_bytes if zip_bytes is not None else zip_del_programa("# nueva\n")
    monkeypatch.setattr(actualizar, "descargar", descargar)


def test_actualiza_sin_tocar_los_datos(instalacion, monkeypatch, capsys):
    github_falso(monkeypatch)
    actualizar.main()
    assert "Programa actualizado (versión del 30/09/2026)" in capsys.readouterr().out
    assert (instalacion / "optica" / "__init__.py").exists()
    assert not (instalacion / "optica" / "viejo.py").exists()
    assert (instalacion / "iniciar.py").read_text().endswith("# nueva\n")
    assert (instalacion / "iniciar-windows.bat").read_text() == "lanzador"
    assert (instalacion / "version.txt").read_text().startswith("abc123")
    # los datos siguen ahí y hay copia de seguridad previa
    conn = sqlite3.connect(instalacion / "datos" / "optica.db")
    assert conn.execute("SELECT nombre FROM clientes").fetchone()[0] == "Ana"
    conn.close()
    assert len(list((instalacion / "datos" / "copias").glob("antes-de-actualizar-*.db"))) == 1


def test_no_hace_nada_si_esta_al_dia(instalacion, monkeypatch, capsys):
    (instalacion / "version.txt").write_text("abc123 2026-09-30\n")
    github_falso(monkeypatch)
    actualizar.main()
    assert "al día" in capsys.readouterr().out
    assert (instalacion / "optica" / "viejo.py").exists()


def test_sin_internet_sigue_con_la_version_actual(instalacion, monkeypatch, capsys):
    def sin_red(url, timeout=10):
        raise OSError("sin conexión")
    monkeypatch.setattr(actualizar, "descargar", sin_red)
    actualizar.main()
    assert "Se usa la versión actual" in capsys.readouterr().out
    assert (instalacion / "optica" / "viejo.py").exists()


def test_descarga_incorrecta_no_rompe_nada(instalacion, monkeypatch, capsys):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("OSV-abc123/otra-cosa.txt", "no es el programa")
    github_falso(monkeypatch, zip_bytes=buffer.getvalue())
    actualizar.main()
    assert "No se ha podido actualizar" in capsys.readouterr().out
    assert (instalacion / "optica" / "viejo.py").exists()
    assert not (instalacion / "version.txt").exists()


def test_reintenta_con_certificados_de_pip(monkeypatch):
    """En los Mac, Python no trae certificados: se usan los que incluye pip."""
    import ssl
    import urllib.error
    llamadas = []

    class Respuesta(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    def urlopen(peticion, timeout=10, context=None):
        llamadas.append(context)
        if context is None:
            raise urllib.error.URLError(ssl.SSLCertVerificationError("certificate verify failed"))
        return Respuesta(b"ok")

    monkeypatch.setattr(actualizar.urllib.request, "urlopen", urlopen)
    assert actualizar.descargar("https://api.github.com/x") == b"ok"
    assert llamadas[0] is None and isinstance(llamadas[1], ssl.SSLContext)


def test_sin_internet_muestra_el_motivo(instalacion, monkeypatch, capsys):
    def sin_red(url, timeout=10):
        raise OSError("sin conexión")
    monkeypatch.setattr(actualizar, "descargar", sin_red)
    actualizar.main()
    assert "Motivo: sin conexión" in capsys.readouterr().out
