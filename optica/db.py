import sqlite3
from pathlib import Path

from flask import current_app, g

SCHEMA = Path(__file__).with_name("schema.sql")


def get_db():
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    # Adaptación a Uruguay: el antiguo 21 % pasa a la tasa básica del 22 %
    conn.execute("UPDATE productos SET iva = 22 WHERE iva = 21")
    # «Montura» pasó a llamarse «Armazón», con sus medidas
    conn.execute("UPDATE productos SET categoria = 'Armazón' WHERE categoria = 'Montura'")
    columnas = {fila[1] for fila in conn.execute("PRAGMA table_info(productos)")}
    for columna in ("calibre", "puente", "diagonal", "altura"):
        if columna not in columnas:
            conn.execute(f"ALTER TABLE productos ADD COLUMN {columna} TEXT NOT NULL DEFAULT ''")
    conn.commit()
    conn.close()


def get_config(db):
    return {r["clave"]: r["valor"] for r in db.execute("SELECT clave, valor FROM configuracion")}


def set_config(db, valores):
    for clave, valor in valores.items():
        db.execute(
            "INSERT INTO configuracion (clave, valor) VALUES (?, ?) "
            "ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor",
            (clave, valor),
        )
