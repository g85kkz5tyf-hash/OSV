import os
import secrets
from pathlib import Path

from flask import Flask

from . import db as database
from .utils import formato_moneda, formato_fecha, formato_importe

RAIZ = Path(__file__).resolve().parent.parent


def create_app(config=None):
    app = Flask(__name__)
    app.config.update(
        DATABASE=os.environ.get("OPTICA_DB", str(RAIZ / "datos" / "optica.db")),
        SECRET_KEY=os.environ.get("OPTICA_SECRET_KEY", secrets.token_hex(16)),
    )
    if config:
        app.config.update(config)

    try:
        sha, fecha = (RAIZ / "version.txt").read_text(encoding="utf-8").split()[:2]
        app.config["VERSION"] = f"{formato_fecha(fecha)} ({sha[:7]})"
    except (OSError, ValueError):
        app.config["VERSION"] = ""

    database.init_db(app.config["DATABASE"])
    app.teardown_appcontext(database.close_db)

    app.jinja_env.filters["moneda"] = formato_moneda
    app.jinja_env.filters["importe"] = formato_importe
    app.jinja_env.filters["fecha"] = formato_fecha

    @app.context_processor
    def datos_tienda():
        config = database.get_config(database.get_db())
        return {"tienda": config, "version": app.config["VERSION"]}

    from .clientes import bp as clientes_bp
    from .main import bp as main_bp
    from .productos import bp as productos_bp
    from .ventas import bp as ventas_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(clientes_bp)
    app.register_blueprint(productos_bp)
    app.register_blueprint(ventas_bp)

    return app
