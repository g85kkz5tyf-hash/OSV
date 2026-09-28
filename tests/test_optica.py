import pytest

from optica import create_app
from optica.db import connect
from optica.utils import desglose_iva, formato_moneda, importe_linea, parse_importe


@pytest.fixture
def app(tmp_path):
    return create_app({"DATABASE": str(tmp_path / "test.db"), "TESTING": True})


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db(app):
    conn = connect(app.config["DATABASE"])
    yield conn
    conn.close()


def crear_cliente(client, **datos):
    datos = {"nombre": "Ana", "apellidos": "García López", "dni": "12345678Z", "telefono": "600111222", **datos}
    r = client.post("/clientes/nuevo", data=datos)
    assert r.status_code == 302
    return int(r.headers["Location"].rstrip("/").split("/")[-1])


def crear_producto(client, codigo="M001", stock="5", controla=True, **extra):
    datos = {
        "codigo": codigo, "categoria": "Armazón", "marca": "Ray-Ban", "modelo": "RB5154",
        "color": "Negro", "precio_coste": "40,00", "precio_venta": "120,00", "iva": "22",
        "stock": stock, "stock_minimo": "1", **extra,
    }
    if controla:
        datos["controla_stock"] = "1"
    r = client.post("/productos/nuevo", data=datos)
    assert r.status_code == 302, r.data
    return int(r.headers["Location"].rstrip("/").split("/")[-1])


def vender(client, lineas, **extra):
    datos = {
        "producto_id": [l.get("producto_id", "") for l in lineas],
        "descripcion": [l.get("descripcion", "") for l in lineas],
        "cantidad": [l.get("cantidad", "1") for l in lineas],
        "precio": [l.get("precio", "0") for l in lineas],
        "descuento": [l.get("descuento", "0") for l in lineas],
        "iva": [l.get("iva", "22") for l in lineas],
        "estado": "Entregado", "metodo": "Efectivo", "pago": "",
        **extra,
    }
    return client.post("/ventas/nueva", data=datos)


# --- Utilidades ---------------------------------------------------------------

def test_parse_importe():
    assert parse_importe("12,50") == 1250
    assert parse_importe("12.5") == 1250
    assert parse_importe("1.234,56") == 123456
    assert parse_importe("") == 0
    assert parse_importe("$ 99") == 9900
    assert parse_importe("1.500") == 150000  # separador de miles
    assert parse_importe("1.500,50") == 150050
    with pytest.raises(ValueError):
        parse_importe("abc")


def test_formato_moneda():
    assert formato_moneda(123456) == "$ 1.234,56"
    assert formato_moneda(5) == "$ 0,05"
    assert formato_moneda(-1050) == "-$ 10,50"


def test_importe_linea_y_desglose():
    assert importe_linea(2, 10000, 10) == 18000
    desglose = desglose_iva([{"iva": 22, "importe": 12200}, {"iva": 10, "importe": 11000}])
    assert desglose == [(10, 10000, 1000, 11000), (22, 10000, 2200, 12200)]


# --- Páginas ----------------------------------------------------------------

@pytest.mark.parametrize("url", [
    "/", "/clientes/", "/clientes/nuevo", "/productos/", "/productos/nuevo",
    "/ventas/", "/ventas/nueva", "/caja", "/informes", "/configuracion",
])
def test_paginas_cargan(client, url):
    assert client.get(url).status_code == 200


# --- Clientes y recetas --------------------------------------------------------

def test_ficha_cliente_con_receta_y_compras(client):
    cid = crear_cliente(client)
    r = client.post(f"/clientes/{cid}/recetas/nueva", data={
        "fecha": "2026-09-01", "tipo": "Gafas progresivas", "optometrista": "Laura",
        "od_esfera": "-1,75", "od_cilindro": "-0,50", "od_eje": "90", "od_adicion": "+2,00",
        "oi_esfera": "-2,00", "oi_cilindro": "-0,75", "oi_eje": "85", "oi_adicion": "+2,00",
        "proxima_revision": "2027-09-01",
    })
    assert r.status_code == 302
    pid = crear_producto(client)
    vender(client, [{"producto_id": str(pid), "descripcion": "Ray-Ban RB5154", "precio": "120,00"}],
           cliente_id=str(cid), receta_id="1", pago="120,00")

    ficha = client.get(f"/clientes/{cid}").get_data(as_text=True)
    assert "Ana García López" in ficha
    assert "-1,75" in ficha and "Gafas progresivas" in ficha
    assert "Ray-Ban RB5154" in ficha  # historial de compras
    assert "$ 120,00" in ficha

    impresa = client.get(f"/clientes/{cid}/recetas/1")
    assert impresa.status_code == 200 and "-2,00" in impresa.get_data(as_text=True)


def test_busqueda_clientes(client):
    crear_cliente(client)
    crear_cliente(client, nombre="Pedro", apellidos="Ruiz", dni="87654321X", telefono="611")
    assert "Pedro" not in client.get("/clientes/?q=García").get_data(as_text=True)
    assert client.get("/clientes/api/buscar?q=876").get_json()[0]["nombre"] == "Pedro Ruiz"


def test_no_se_elimina_cliente_con_ventas(client, db):
    cid = crear_cliente(client)
    vender(client, [{"descripcion": "Revisión", "precio": "20"}], cliente_id=str(cid))
    client.post(f"/clientes/{cid}/eliminar")
    assert db.execute("SELECT COUNT(*) FROM clientes").fetchone()[0] == 1


# --- Stock ----------------------------------------------------------------------

def test_producto_stock_inicial_entrada_y_recuento(client, db):
    pid = crear_producto(client, stock="3")
    client.post(f"/productos/{pid}/movimiento", data={"tipo": "entrada", "cantidad": "4"})
    assert db.execute("SELECT stock FROM productos WHERE id=?", (pid,)).fetchone()[0] == 7
    client.post(f"/productos/{pid}/movimiento", data={"tipo": "recuento", "cantidad": "6", "motivo": "Rotura"})
    assert db.execute("SELECT stock FROM productos WHERE id=?", (pid,)).fetchone()[0] == 6
    movs = db.execute("SELECT tipo, cantidad FROM movimientos_stock ORDER BY id").fetchall()
    assert [tuple(m) for m in movs] == [("entrada", 3), ("entrada", 4), ("ajuste", -1)]


def test_codigo_producto_duplicado(client, db):
    crear_producto(client, codigo="X1")
    r = client.post("/productos/nuevo", data={"codigo": "X1", "categoria": "Armazón"})
    assert r.status_code == 200
    assert "Ya existe" in r.get_data(as_text=True)
    assert db.execute("SELECT COUNT(*) FROM productos").fetchone()[0] == 1


def test_stock_bajo_en_inicio(client):
    crear_producto(client, codigo="BAJO", stock="1", modelo="ModeloEscaso")
    assert "ModeloEscaso" in client.get("/").get_data(as_text=True)


def test_exportar_csv(client):
    crear_producto(client)
    r = client.get("/productos/exportar.csv")
    assert r.status_code == 200
    assert "RB5154" in r.get_data(as_text=True)


# --- Ventas ---------------------------------------------------------------------

def test_venta_descuenta_stock_y_registra_pago(client, db):
    pid = crear_producto(client, stock="5")
    r = vender(client, [
        {"producto_id": str(pid), "descripcion": "Ray-Ban", "cantidad": "2", "precio": "120,00", "descuento": "10"},
        {"descripcion": "Lentes progresivas a medida", "precio": "300", "iva": "10"},
    ], pago="100", estado="En taller")
    assert r.status_code == 302
    venta = db.execute("SELECT * FROM ventas").fetchone()
    assert venta["total"] == 21600 + 30000
    assert venta["estado"] == "En taller"
    assert db.execute("SELECT stock FROM productos WHERE id=?", (pid,)).fetchone()[0] == 3
    assert db.execute("SELECT SUM(importe) FROM pagos").fetchone()[0] == 10000
    # la línea de producto toma el IVA del producto aunque el formulario diga otro
    ivas = [r[0] for r in db.execute("SELECT iva FROM lineas_venta ORDER BY id")]
    assert ivas == [22, 10]

    detalle = client.get(f"/ventas/{venta['id']}").get_data(as_text=True)
    assert "$ 416,00" in detalle  # pendiente
    assert client.get(f"/ventas/{venta['id']}/ticket").status_code == 200

    # cobrar el resto
    client.post(f"/ventas/{venta['id']}/pago", data={"importe": "416,00", "metodo": "Tarjeta"})
    assert db.execute("SELECT SUM(importe) FROM pagos").fetchone()[0] == venta["total"]
    # no se puede cobrar de más
    client.post(f"/ventas/{venta['id']}/pago", data={"importe": "1", "metodo": "Tarjeta"})
    assert db.execute("SELECT COUNT(*) FROM pagos").fetchone()[0] == 2


def test_venta_sin_stock_suficiente_no_se_registra(client, db):
    pid = crear_producto(client, stock="1")
    r = vender(client, [{"producto_id": str(pid), "cantidad": "2", "precio": "120"}])
    assert r.status_code == 200
    assert "No hay stock suficiente" in r.get_data(as_text=True)
    assert db.execute("SELECT COUNT(*) FROM ventas").fetchone()[0] == 0
    assert db.execute("SELECT stock FROM productos WHERE id=?", (pid,)).fetchone()[0] == 1


def test_producto_sin_control_de_stock_se_vende_siempre(client, db):
    pid = crear_producto(client, codigo="LENTE", stock="0", controla=False)
    r = vender(client, [{"producto_id": str(pid), "cantidad": "2", "precio": "80"}])
    assert r.status_code == 302
    assert db.execute("SELECT stock FROM productos WHERE id=?", (pid,)).fetchone()[0] == 0


def test_pago_superior_al_total_rechazado(client, db):
    r = vender(client, [{"descripcion": "Servicio", "precio": "10"}], pago="20")
    assert r.status_code == 200
    assert db.execute("SELECT COUNT(*) FROM ventas").fetchone()[0] == 0


def test_receta_de_otro_cliente_rechazada(client, db):
    c1 = crear_cliente(client)
    c2 = crear_cliente(client, nombre="Luis")
    client.post(f"/clientes/{c1}/recetas/nueva", data={"fecha": "2026-01-01"})
    r = vender(client, [{"descripcion": "Gafas", "precio": "10"}], cliente_id=str(c2), receta_id="1")
    assert r.status_code == 200
    assert db.execute("SELECT COUNT(*) FROM ventas").fetchone()[0] == 0


def test_anular_venta_repone_stock_y_devuelve_pagos(client, db):
    pid = crear_producto(client, stock="2")
    vender(client, [{"producto_id": str(pid), "precio": "120"}], pago="120", metodo="Tarjeta")
    assert db.execute("SELECT stock FROM productos").fetchone()[0] == 1
    client.post("/ventas/1/anular", data={"motivo": "Devolución"})
    assert db.execute("SELECT stock FROM productos").fetchone()[0] == 2
    assert db.execute("SELECT estado FROM ventas").fetchone()[0] == "Anulada"
    pagos = db.execute("SELECT importe, metodo FROM pagos ORDER BY id").fetchall()
    assert [tuple(p) for p in pagos] == [(12000, "Tarjeta"), (-12000, "Tarjeta")]
    # anular dos veces no está permitido
    assert client.post("/ventas/1/anular").status_code == 400


def test_numeracion_correlativa(client, db):
    for _ in range(3):
        vender(client, [{"descripcion": "Servicio", "precio": "5"}])
    numeros = [r[0] for r in db.execute("SELECT numero FROM ventas ORDER BY id")]
    assert [n.split("-")[1] for n in numeros] == ["00001", "00002", "00003"]


def test_caja_por_metodo(client):
    vender(client, [{"descripcion": "A", "precio": "10"}], pago="10", metodo="Efectivo")
    vender(client, [{"descripcion": "B", "precio": "25,50"}], pago="25,50", metodo="Transferencia")
    html = client.get("/caja").get_data(as_text=True)
    assert "$ 35,50" in html and "$ 25,50" in html
    assert "Bizum" not in html


def test_configuracion_y_copia(client):
    client.post("/configuracion", data={"nombre": "Óptica Sol", "nif": "B12345678"})
    assert "Óptica Sol" in client.get("/").get_data(as_text=True)
    r = client.get("/copia-seguridad")
    assert r.status_code == 200 and r.data[:15] == b"SQLite format 3"


def test_cambio_rapido_de_estado_desde_inicio(client, db):
    vender(client, [{"descripcion": "Gafas graduadas", "precio": "200"}],
           estado="En taller", notas="Montaje al aire", fecha_entrega_prevista="2026-10-10")
    inicio = client.get("/").get_data(as_text=True)
    assert 'class="cambio-estado"' in inicio

    r = client.post("/ventas/1/cambiar-estado", data={"estado": "Listo para recoger", "volver": "/"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/")
    venta = db.execute("SELECT estado, notas, fecha_entrega_prevista FROM ventas").fetchone()
    # cambia el estado sin perder las notas ni la fecha de entrega
    assert tuple(venta) == ("Listo para recoger", "Montaje al aire", "2026-10-10")

    client.post("/ventas/1/cambiar-estado", data={"estado": "Entregado", "volver": "/"})
    assert "Gafas graduadas" not in client.get("/").get_data(as_text=True)  # sale de encargos en curso


def test_cambio_rapido_de_estado_validaciones(client, db):
    vender(client, [{"descripcion": "Gafas", "precio": "50"}], estado="Pendiente")
    assert client.post("/ventas/1/cambiar-estado", data={"estado": "Anulada"}).status_code == 400
    assert client.post("/ventas/1/cambiar-estado", data={"estado": "Inventado"}).status_code == 400
    # no redirige a webs externas
    r = client.post("/ventas/1/cambiar-estado", data={"estado": "En taller", "volver": "//malo.com"})
    assert r.headers["Location"] == "/"


def test_migracion_iva_21_a_22(tmp_path):
    ruta = str(tmp_path / "vieja.db")
    create_app({"DATABASE": ruta})
    conn = connect(ruta)
    conn.execute("INSERT INTO productos (codigo, categoria, iva) VALUES ('A', 'Montura', 21)")
    conn.commit()
    create_app({"DATABASE": ruta})  # al volver a abrir el programa
    assert conn.execute("SELECT iva FROM productos").fetchone()[0] == 22
    conn.close()


def test_orden_de_venta(client, db):
    cid = crear_cliente(client)
    client.post(f"/clientes/{cid}/recetas/nueva", data={"fecha": "2026-09-01", "od_esfera": "+1,50", "oi_esfera": "-2,00"})
    pid = crear_producto(client)
    r = vender(client, [{"producto_id": str(pid), "descripcion": "Ray-Ban RB5154", "precio": "4.500"}],
               cliente_id=str(cid), receta_id="1", fecha_entrega_prevista="2026-10-05", accion="orden")
    assert r.status_code == 302 and r.headers["Location"].endswith("/ventas/1/orden")
    html = client.get("/ventas/1/orden").get_data(as_text=True)
    for texto in ["ORDEN DE TRABAJO", "Ana García López", "600111222", "Ray-Ban RB5154", "+1,50", "-2,00",
                  "05/10/2026", "$ 4.500,00", "SEÑA", "SALDO"]:
        assert texto in html, texto
    assert "Generar orden de trabajo" in client.get("/ventas/1").get_data(as_text=True)


def test_orden_de_venta_sin_cliente_ni_receta(client):
    vender(client, [{"descripcion": "Líquido", "precio": "300"}])
    assert client.get("/ventas/1/orden").status_code == 200


def test_cerrar_requiere_clave(app, client, monkeypatch):
    import optica.main
    cierres = []
    monkeypatch.setattr(optica.main.threading, "Timer", lambda *a: type("T", (), {"start": lambda s: cierres.append(1)})())
    assert client.post("/cerrar", data={"clave": "x"}).status_code == 403  # sin clave configurada
    app.config["CLAVE_CIERRE"] = "secreta"
    assert client.post("/cerrar", data={"clave": "otra"}).status_code == 403
    assert client.get("/cerrar").status_code == 405
    assert not cierres
    assert client.post("/cerrar", data={"clave": "secreta"}).status_code == 200
    assert cierres == [1]


def test_version_en_el_pie(client):
    assert "Versión" in client.get("/").get_data(as_text=True)


def test_medidas_del_armazon(client, db):
    pid = crear_producto(client, calibre="52", puente="18", diagonal="55", altura="40")
    fila = db.execute("SELECT categoria, calibre, puente, diagonal, altura FROM productos WHERE id=?", (pid,)).fetchone()
    assert tuple(fila) == ("Armazón", "52", "18", "55", "40")
    detalle = client.get(f"/productos/{pid}").get_data(as_text=True)
    assert "Calibre (C)" in detalle and "55" in detalle
    # en otras categorías no se guardan medidas
    pid2 = crear_producto(client, codigo="SOL1", categoria="Gafa de sol", calibre="60")
    assert db.execute("SELECT calibre FROM productos WHERE id=?", (pid2,)).fetchone()[0] == ""


def test_orden_de_trabajo_con_medidas(client):
    cid = crear_cliente(client)
    pid = crear_producto(client, calibre="52", puente="18", diagonal="55", altura="40")
    vender(client, [{"producto_id": str(pid), "descripcion": "Ray-Ban RB5154", "precio": "4500"}], cliente_id=str(cid))
    html = client.get("/ventas/1/orden").get_data(as_text=True)
    assert "ORDEN DE TRABAJO" in html and "ORDEN DE VENTA" not in html
    for inicial, valor in [("c", "52"), ("p", "18"), ("d", "55"), ("a", "40")]:
        assert f"<b>{inicial}</b> {valor}" in html


def test_migracion_montura_a_armazon(tmp_path):
    ruta = str(tmp_path / "vieja.db")
    conn = connect(ruta)
    # tabla de productos tal como era antes de las medidas
    conn.execute("""CREATE TABLE productos (id INTEGER PRIMARY KEY AUTOINCREMENT, codigo TEXT NOT NULL UNIQUE,
        categoria TEXT NOT NULL, marca TEXT NOT NULL DEFAULT '', modelo TEXT NOT NULL DEFAULT '',
        color TEXT NOT NULL DEFAULT '', descripcion TEXT NOT NULL DEFAULT '', proveedor TEXT NOT NULL DEFAULT '',
        precio_coste INTEGER NOT NULL DEFAULT 0, precio_venta INTEGER NOT NULL DEFAULT 0,
        iva INTEGER NOT NULL DEFAULT 21, stock INTEGER NOT NULL DEFAULT 0, stock_minimo INTEGER NOT NULL DEFAULT 0,
        controla_stock INTEGER NOT NULL DEFAULT 1, activo INTEGER NOT NULL DEFAULT 1,
        creado TEXT NOT NULL DEFAULT (datetime('now', 'localtime')))""")
    conn.execute("INSERT INTO productos (codigo, categoria) VALUES ('M1', 'Montura')")
    conn.commit()
    app = create_app({"DATABASE": ruta})
    assert tuple(conn.execute("SELECT categoria, calibre FROM productos").fetchone()) == ("Armazón", "")
    conn.close()
    assert app.test_client().get("/productos/1/editar").status_code == 200


@pytest.mark.parametrize("lugar,laboratorio,guardado,color", [
    ("taller", "", "Taller propio", "#e10600"),
    ("laboratorio", "Vidaltec", "Vidaltec", "#1e9e3a"),
    ("laboratorio", "Camponac", "Camponac", "#38bdf8"),
    ("laboratorio", "Rodenstock", "Rodenstock", "#1d4ed8"),
    ("laboratorio", "Jiki", "Jiki", "#7e22ce"),
])
def test_donde_se_ejecuta_y_color_en_la_orden(client, db, lugar, laboratorio, guardado, color):
    r = vender(client, [{"descripcion": "Lentes", "precio": "3000"}], lugar=lugar, laboratorio=laboratorio)
    assert r.status_code == 302
    assert db.execute("SELECT ejecucion FROM ventas").fetchone()[0] == guardado
    html = client.get("/ventas/1/orden").get_data(as_text=True)
    assert f'class="color-ejecucion" style="background: {color}"' in html


def test_laboratorio_obligatorio_si_va_a_laboratorio(client, db):
    r = vender(client, [{"descripcion": "Lentes", "precio": "3000"}], lugar="laboratorio", laboratorio="")
    assert r.status_code == 200 and "Elige en qué laboratorio" in r.get_data(as_text=True)
    assert db.execute("SELECT COUNT(*) FROM ventas").fetchone()[0] == 0
    r = vender(client, [{"descripcion": "Lentes", "precio": "3000"}], lugar="laboratorio", laboratorio="Otro")
    assert r.status_code == 200


def test_sin_lugar_no_hay_recuadro(client):
    vender(client, [{"descripcion": "Líquido", "precio": "300"}])
    assert 'class="color-ejecucion"' not in client.get("/ventas/1/orden").get_data(as_text=True)


def test_cambiar_laboratorio_desde_la_ficha(client, db):
    vender(client, [{"descripcion": "Lentes", "precio": "3000"}], lugar="taller", estado="En taller")
    client.post("/ventas/1/estado", data={"estado": "En taller", "lugar": "laboratorio", "laboratorio": "Jiki"})
    assert db.execute("SELECT ejecucion FROM ventas").fetchone()[0] == "Jiki"
    ficha = client.get("/ventas/1").get_data(as_text=True)
    assert '<option selected>Jiki</option>' in ficha


def test_cobro_con_varios_medios_al_registrar(client, db):
    r = vender(client, [{"descripcion": "Lentes", "precio": "5000"}],
               pago=["2000", "1.500", ""], metodo=["Efectivo", "Prestación", "Tarjeta"])
    assert r.status_code == 302
    pagos = [tuple(p) for p in db.execute("SELECT importe, metodo FROM pagos ORDER BY id")]
    assert pagos == [(200000, "Efectivo"), (150000, "Prestación")]  # la fila vacía se ignora


def test_cobro_con_varios_medios_superior_al_total(client, db):
    r = vender(client, [{"descripcion": "Lentes", "precio": "5000"}],
               pago=["3000", "3000"], metodo=["Efectivo", "Tarjeta"])
    assert r.status_code == 200 and "no puede superar el total" in r.get_data(as_text=True)
    assert db.execute("SELECT COUNT(*) FROM ventas").fetchone()[0] == 0


def test_cobrar_el_saldo_con_varios_medios(client, db):
    vender(client, [{"descripcion": "Lentes", "precio": "5000"}], pago="1000", metodo="Efectivo", estado="En taller")
    r = client.post("/ventas/1/pago", data={"importe": ["2500", "1500"], "metodo": ["Tarjeta", "Prestación"]},
                    follow_redirects=True)
    assert "2 cobros registrados" in r.get_data(as_text=True)
    assert db.execute("SELECT SUM(importe) FROM pagos").fetchone()[0] == 500000
    # no se puede cobrar de más aunque se reparta
    client.post("/ventas/1/pago", data={"importe": ["1", "1"], "metodo": ["Tarjeta", "Efectivo"]})
    assert db.execute("SELECT COUNT(*) FROM pagos").fetchone()[0] == 3
    caja = client.get("/caja").get_data(as_text=True)
    assert "Prestación" in caja and "$ 1.500,00" in caja


def test_medio_de_pago_invalido(client, db):
    r = vender(client, [{"descripcion": "Lentes", "precio": "5000"}], pago="100", metodo="Bizum")
    assert r.status_code == 200
    assert db.execute("SELECT COUNT(*) FROM ventas").fetchone()[0] == 0


def test_tareas_pendientes_del_taller_propio(client):
    vender(client, [{"descripcion": "Trabajo taller pendiente"}], lugar="taller", estado="Pendiente")
    vender(client, [{"descripcion": "Trabajo taller en curso"}], lugar="taller", estado="En taller")
    vender(client, [{"descripcion": "Trabajo taller listo"}], lugar="taller", estado="Listo para recoger")
    vender(client, [{"descripcion": "Trabajo de laboratorio"}], lugar="laboratorio", laboratorio="Jiki", estado="En taller")
    inicio = client.get("/").get_data(as_text=True)
    tareas = inicio.split("Tareas pendientes", 1)[1]
    assert "Revisiones próximas" not in inicio
    assert "Tareas pendientes (2)" in inicio
    assert "Trabajo taller pendiente" in tareas and "Trabajo taller en curso" in tareas
    assert "Trabajo taller listo" not in tareas and "Trabajo de laboratorio" not in tareas
    # al marcarla como lista, sale de las tareas
    client.post("/ventas/2/cambiar-estado", data={"estado": "Listo para recoger"})
    assert "Tareas pendientes (1)" in client.get("/").get_data(as_text=True)
