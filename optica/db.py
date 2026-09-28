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
    # «Gafas» pasó a llamarse «Lentes»
    conn.execute("UPDATE recetas SET tipo = 'Lentes' || substr(tipo, 6) WHERE tipo LIKE 'Gafas %'")
    conn.execute("UPDATE productos SET categoria = 'Lentes de sol' WHERE categoria = 'Gafa de sol'")
    # «Progresivas» pasó a «Multifocales» y «Lente oftálmica» a «Cristales»
    conn.execute("UPDATE recetas SET tipo = 'Lentes multifocales' WHERE tipo = 'Lentes progresivas'")
    conn.execute("UPDATE productos SET categoria = 'Cristales' WHERE categoria = 'Lente oftálmica'")
    # «Montura» pasó a llamarse «Armazón», con sus medidas
    conn.execute("UPDATE productos SET categoria = 'Armazón' WHERE categoria = 'Montura'")
    nuevas_columnas = {
        "productos": ["calibre", "puente", "diagonal", "altura"],
        "ventas": ["ejecucion", "numero_trabajo"],  # taller o laboratorio, y nº del laboratorio
        "lineas_venta": ["calibre", "puente", "diagonal", "altura", "ranurado",  # armazón propio
                         ("receta_id", "INTEGER REFERENCES recetas(id)")],  # receta de cada lente
        "venta_recetas": ["numero_trabajo"],  # nº de trabajo por receta si hay varias
    }
    for tabla, nuevas in nuevas_columnas.items():
        columnas = {fila[1] for fila in conn.execute(f"PRAGMA table_info({tabla})")}
        for columna in nuevas:
            columna, definicion = columna if isinstance(columna, tuple) else (columna, "TEXT NOT NULL DEFAULT ''")
            if columna not in columnas:
                conn.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {definicion}")
    # Producto «Armazón propio» (costo y precio 0, sin control de stock)
    conn.execute(
        "INSERT OR IGNORE INTO productos (codigo, categoria, descripcion, precio_coste, precio_venta,"
        " controla_stock) VALUES ('ARMAZON-PROPIO', 'Armazón', 'Armazón propio', 0, 0, 0)"
    )
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
