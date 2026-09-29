import pytest

from optica import create_app
from optica.db import connect
from optica.utils import formato_moneda, importe_linea, parse_importe


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


def test_importe_linea():
    assert importe_linea(2, 10000, 10) == 18000


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
        "fecha": "2026-09-01", "tipo": "Lentes multifocales", "optometrista": "Laura",
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
    assert "-1,75" in ficha and "Lentes multifocales" in ficha
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
    assert db.execute("SELECT COUNT(*) FROM productos WHERE codigo = 'X1'").fetchone()[0] == 1


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
        {"descripcion": "Lentes multifocales a medida", "precio": "300", "iva": "10"},
    ], pago="100", estado="En taller")
    assert r.status_code == 302
    venta = db.execute("SELECT * FROM ventas").fetchone()
    assert venta["total"] == 21600 + 30000
    assert venta["estado"] == "En taller"
    assert db.execute("SELECT stock FROM productos WHERE id=?", (pid,)).fetchone()[0] == 3
    assert db.execute("SELECT SUM(importe) FROM pagos").fetchone()[0] == 10000

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
    r = vender(client, [{"descripcion": "Lentes", "precio": "10"}], cliente_id=str(c2), receta_id="1")
    assert r.status_code == 200
    assert db.execute("SELECT COUNT(*) FROM ventas").fetchone()[0] == 0


def test_anular_venta_repone_stock_y_devuelve_pagos(client, db):
    pid = crear_producto(client, stock="2")
    vender(client, [{"producto_id": str(pid), "precio": "120"}], pago="120", metodo="Tarjeta")
    assert db.execute("SELECT stock FROM productos WHERE id = ?", (pid,)).fetchone()[0] == 1
    client.post("/ventas/1/anular", data={"motivo": "Devolución"})
    assert db.execute("SELECT stock FROM productos WHERE id = ?", (pid,)).fetchone()[0] == 2
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
    vender(client, [{"descripcion": "Lentes graduadas", "precio": "200"}],
           estado="En taller", notas="Montaje al aire", fecha_entrega_prevista="2026-10-10")
    inicio = client.get("/").get_data(as_text=True)
    assert 'class="cambio-estado"' in inicio

    r = client.post("/ventas/1/cambiar-estado", data={"estado": "Listo para recoger", "volver": "/"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/")
    venta = db.execute("SELECT estado, notas, fecha_entrega_prevista FROM ventas").fetchone()
    # cambia el estado sin perder las notas ni la fecha de entrega
    assert tuple(venta) == ("Listo para recoger", "Montaje al aire", "2026-10-10")

    client.post("/ventas/1/cambiar-estado", data={"estado": "Entregado", "volver": "/"})
    assert "Lentes graduadas" not in client.get("/").get_data(as_text=True)  # sale de encargos en curso


def test_cambio_rapido_de_estado_validaciones(client, db):
    vender(client, [{"descripcion": "Lentes", "precio": "50"}], estado="Pendiente")
    assert client.post("/ventas/1/cambiar-estado", data={"estado": "Anulada"}).status_code == 400
    assert client.post("/ventas/1/cambiar-estado", data={"estado": "Inventado"}).status_code == 400
    # no redirige a webs externas
    r = client.post("/ventas/1/cambiar-estado", data={"estado": "En taller", "volver": "//malo.com"})
    assert r.headers["Location"] == "/"


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
    pid2 = crear_producto(client, codigo="SOL1", categoria="Lentes de sol", calibre="60")
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


def test_cobro_rapido_desde_inicio(client, db):
    vender(client, [{"descripcion": "Lentes", "precio": "5000"}], pago="1000", estado="En taller")
    inicio = client.get("/").get_data(as_text=True)
    assert 'class="peque boton-cobrar"' in inicio and 'id="cobro-1"' in inicio
    r = client.post("/ventas/1/pago", data={"importe": ["3000", "1000"], "metodo": ["Efectivo", "Prestación"],
                                             "volver": "/"})
    assert r.status_code == 302 and r.headers["Location"] == "/"
    assert db.execute("SELECT SUM(importe) FROM pagos").fetchone()[0] == 500000
    # saldada: ya no aparece el botón
    assert 'id="cobro-1"' not in client.get("/").get_data(as_text=True)
    # si hay error también vuelve a inicio, y nunca a otra web
    r = client.post("/ventas/1/pago", data={"importe": "1", "metodo": "Efectivo", "volver": "//malo.com"})
    assert r.headers["Location"] == "/ventas/1"


def test_compras_anteriores_no_afectan_datos(client, db):
    cid = crear_cliente(client)
    r = client.post(f"/clientes/{cid}/compras-anteriores", data={
        "fecha": "2021-05-10", "descripcion": "Armazón Vogue + cristales monofocales",
        "importe": "4.500", "observaciones": "OD -1,00 OI -1,25"})
    assert r.status_code == 302
    client.post(f"/clientes/{cid}/compras-anteriores", data={"descripcion": "Lentes de contacto mensuales"})
    ficha = client.get(f"/clientes/{cid}").get_data(as_text=True)
    assert "Compras anteriores al programa (2)" in ficha
    assert "Armazón Vogue + cristales monofocales" in ficha and "$ 4.500,00" in ficha
    assert "10/05/2021" in ficha and "Lentes de contacto mensuales" in ficha
    # nada de esto aparece en ventas, caja, informes ni en el total del cliente
    assert db.execute("SELECT COUNT(*) FROM ventas").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM pagos").fetchone()[0] == 0
    assert "Armazón Vogue" not in client.get("/informes?anio=2021").get_data(as_text=True)
    assert "No hay ventas" in client.get("/ventas/").get_data(as_text=True)
    assert "$ 0,00" in ficha.split("Total comprado", 1)[1][:200]


def test_editar_y_eliminar_compra_anterior(client, db):
    cid = crear_cliente(client)
    client.post(f"/clientes/{cid}/compras-anteriores", data={"descripcion": "Lentes de sol", "importe": "2000"})
    assert client.get(f"/clientes/{cid}/compras-anteriores/1/editar").status_code == 200
    client.post(f"/clientes/{cid}/compras-anteriores/1/editar", data={"descripcion": "Lentes de sol Ray-Ban", "importe": ""})
    fila = db.execute("SELECT descripcion, importe FROM compras_anteriores").fetchone()
    assert tuple(fila) == ("Lentes de sol Ray-Ban", None)
    client.post(f"/clientes/{cid}/compras-anteriores/1/eliminar")
    assert db.execute("SELECT COUNT(*) FROM compras_anteriores").fetchone()[0] == 0


def test_compra_anterior_requiere_descripcion(client, db):
    cid = crear_cliente(client)
    r = client.post(f"/clientes/{cid}/compras-anteriores", data={"descripcion": " "}, follow_redirects=True)
    assert "Escribe qué compró" in r.get_data(as_text=True)
    assert db.execute("SELECT COUNT(*) FROM compras_anteriores").fetchone()[0] == 0
    # no se pueden tocar compras de otro cliente
    otro = crear_cliente(client, nombre="Luis")
    client.post(f"/clientes/{cid}/compras-anteriores", data={"descripcion": "Armazón"})
    assert client.post(f"/clientes/{otro}/compras-anteriores/1/eliminar").status_code == 404


def test_numero_de_trabajo_del_laboratorio(client, db):
    cid = crear_cliente(client)
    vender(client, [{"descripcion": "Progresivos"}], cliente_id=str(cid), lugar="laboratorio",
           laboratorio="Vidaltec", estado="En taller")
    vender(client, [{"descripcion": "Monofocales"}], cliente_id=str(cid), lugar="taller", estado="En taller")
    inicio = client.get("/").get_data(as_text=True)
    # el pulsador solo aparece en la venta de laboratorio
    assert inicio.count("+ Nº de trabajo") == 1 and 'id="trabajo-1"' in inicio and 'id="trabajo-2"' not in inicio

    r = client.post("/ventas/1/numero-trabajo", data={"numero_trabajo": " VT-4589 ", "volver": "/"})
    assert r.status_code == 302 and r.headers["Location"] == "/"
    assert db.execute("SELECT numero_trabajo FROM ventas WHERE id = 1").fetchone()[0] == "VT-4589"
    inicio = client.get("/").get_data(as_text=True)
    assert "+ Nº de trabajo" not in inicio and "Nº VT-4589" in inicio

    ficha = client.get(f"/clientes/{cid}").get_data(as_text=True)
    assert "Laboratorio Vidaltec" in ficha and "Nº de trabajo: VT-4589" in ficha
    assert "Taller propio" in ficha


def test_numero_de_trabajo_validaciones(client, db):
    vender(client, [{"descripcion": "Monofocales"}], lugar="taller", estado="En taller")
    r = client.post("/ventas/1/numero-trabajo", data={"numero_trabajo": "123"}, follow_redirects=True)
    assert "no se ejecuta en un laboratorio" in r.get_data(as_text=True)
    vender(client, [{"descripcion": "Progresivos"}], lugar="laboratorio", laboratorio="Jiki", estado="En taller")
    r = client.post("/ventas/2/numero-trabajo", data={"numero_trabajo": "  "}, follow_redirects=True)
    assert "Escribe el número de trabajo" in r.get_data(as_text=True)
    assert db.execute("SELECT numero_trabajo FROM ventas WHERE id = 2").fetchone()[0] == ""


def test_numero_de_trabajo_se_corrige_desde_la_ficha(client, db):
    vender(client, [{"descripcion": "Progresivos"}], lugar="laboratorio", laboratorio="Jiki", estado="En taller")
    client.post("/ventas/1/numero-trabajo", data={"numero_trabajo": "111"})
    assert 'value="111"' in client.get("/ventas/1").get_data(as_text=True)
    client.post("/ventas/1/estado", data={"estado": "En taller", "lugar": "laboratorio", "laboratorio": "Jiki",
                                          "numero_trabajo": "112"})
    assert db.execute("SELECT numero_trabajo FROM ventas").fetchone()[0] == "112"
    # si pasa a taller propio, el número del laboratorio se borra
    client.post("/ventas/1/estado", data={"estado": "En taller", "lugar": "taller", "numero_trabajo": "112"})
    assert db.execute("SELECT numero_trabajo FROM ventas").fetchone()[0] == ""


def test_aviso_de_entregas_vencidas(client, db):
    from datetime import date, timedelta
    ayer = (date.today() - timedelta(days=1)).isoformat()
    hoy = date.today().isoformat()
    vender(client, [{"descripcion": "Atrasado"}], estado="En taller", fecha_entrega_prevista=ayer)
    vender(client, [{"descripcion": "Vence hoy"}], estado="En taller", fecha_entrega_prevista=hoy)
    vender(client, [{"descripcion": "Listo a tiempo"}], estado="Listo para recoger", fecha_entrega_prevista=ayer)
    vender(client, [{"descripcion": "Sin fecha"}], estado="Pendiente")
    inicio = client.get("/").get_data(as_text=True)
    assert "1 trabajo con la entrega vencida" in inicio
    aviso = inicio.split('class="aviso-atrasados"', 1)[1]
    assert "/ventas/1" in aviso and "/ventas/2" not in aviso and "/ventas/3" not in aviso and "/ventas/4" not in aviso
    # cambiar a «Pendiente» no lo quita; «Listo para recoger» sí
    client.post("/ventas/1/cambiar-estado", data={"estado": "Pendiente"})
    assert 'class="aviso-atrasados"' in client.get("/").get_data(as_text=True)
    client.post("/ventas/1/cambiar-estado", data={"estado": "Listo para recoger"})
    assert 'class="aviso-atrasados"' not in client.get("/").get_data(as_text=True)


def test_armazon_propio_con_medidas_en_la_orden(client, db):
    propio = db.execute("SELECT * FROM productos WHERE codigo = 'ARMAZON-PROPIO'").fetchone()
    assert propio["precio_coste"] == 0 and propio["precio_venta"] == 0 and propio["controla_stock"] == 0
    assert client.get("/productos/api/buscar?q=propio").get_json()[0]["armazon_propio"] is True

    cid = crear_cliente(client)
    datos = {
        "cliente_id": str(cid), "producto_id": [str(propio["id"]), ""],
        "descripcion": ["Armazón propio", "Cristales monofocales"], "cantidad": ["1", "1"],
        "precio": ["0", "3500"], "descuento": ["0", "0"], "iva": ["22", "22"],
        "medida_calibre": ["52", "99"], "medida_puente": ["18", ""], "medida_diagonal": ["", ""],
        "medida_altura": ["38", ""], "estado": "En taller", "pago": "", "metodo": "Efectivo",
    }
    assert client.post("/ventas/nueva", data=datos).status_code == 302
    lineas = db.execute("SELECT calibre, puente, diagonal, altura FROM lineas_venta ORDER BY id").fetchall()
    assert tuple(lineas[0]) == ("52", "18", "", "38")
    assert tuple(lineas[1]) == ("", "", "", "")  # la línea de cristales no guarda medidas
    orden = client.get("/ventas/1/orden").get_data(as_text=True)
    assert "<b>c</b> 52" in orden and "<b>p</b> 18" in orden and "<b>d</b> ____" in orden and "<b>a</b> 38" in orden

    # completar la diagonal desde la ficha de la venta
    linea_id = db.execute("SELECT id FROM lineas_venta ORDER BY id").fetchone()[0]
    assert 'name="ranurado"' in client.get("/ventas/1").get_data(as_text=True)
    client.post(f"/ventas/1/medidas/{linea_id}", data={"calibre": "52", "puente": "18", "diagonal": "54", "altura": "38"})
    assert "<b>d</b> 54" in client.get("/ventas/1/orden").get_data(as_text=True)
    # la línea de cristales no admite medidas
    otra = db.execute("SELECT id FROM lineas_venta ORDER BY id DESC").fetchone()[0]
    assert client.post(f"/ventas/1/medidas/{otra}", data={"calibre": "1"}).status_code == 404


def test_armazon_propio_no_se_duplica(tmp_path):
    ruta = str(tmp_path / "x.db")
    create_app({"DATABASE": ruta})
    create_app({"DATABASE": ruta})
    conn = connect(ruta)
    assert conn.execute("SELECT COUNT(*) FROM productos WHERE codigo = 'ARMAZON-PROPIO'").fetchone()[0] == 1
    conn.close()


def test_receta_de_cerca_automatica(client, db):
    cid = crear_cliente(client)
    r = client.post(f"/clientes/{cid}/recetas/nueva", data={
        "fecha": "2026-09-20", "tipo": "Lentes lejos", "optometrista": "Laura",
        "od_esfera": "-1,75", "od_cilindro": "-0,50", "od_eje": "90", "od_adicion": "+2,00", "od_dnp": "31",
        "oi_esfera": "+0,50", "oi_cilindro": "", "oi_eje": "", "oi_adicion": "2,25", "oi_dnp": "30,5",
        "observaciones": "Control anual", "generar_cerca": "1",
    }, follow_redirects=True)
    assert "También se creó la receta para lentes de cerca" in r.get_data(as_text=True)
    recetas = db.execute("SELECT * FROM recetas ORDER BY id").fetchall()
    assert len(recetas) == 2
    cerca, lejos = recetas  # la escrita queda como la más reciente («Actual»)
    assert lejos["tipo"] == "Lentes lejos" and lejos["od_esfera"] == "-1,75" and lejos["od_adicion"] == "+2,00"
    assert cerca["tipo"] == "Lentes cerca"
    assert cerca["od_esfera"] == "+0,25" and cerca["oi_esfera"] == "+2,75"
    assert cerca["od_adicion"] == "" and cerca["oi_adicion"] == ""
    # el resto es idéntico
    for campo in ("fecha", "optometrista", "od_cilindro", "od_eje", "od_dnp", "oi_dnp", "observaciones"):
        assert cerca[campo] == lejos[campo], campo


def test_receta_de_cerca_casos(client, db):
    cid = crear_cliente(client)
    # sin marcar «generar_cerca» no se crea
    client.post(f"/clientes/{cid}/recetas/nueva", data={"tipo": "Lentes lejos", "od_esfera": "-1,00", "od_adicion": "+1,00"})
    assert db.execute("SELECT COUNT(*) FROM recetas").fetchone()[0] == 1
    # esfera vacía o neutra = 0; esfera que queda en cero
    client.post(f"/clientes/{cid}/recetas/nueva", data={
        "tipo": "Lentes lejos", "od_esfera": "", "od_adicion": "+1,50", "oi_esfera": "-1,00", "oi_adicion": "+1,00", "generar_cerca": "1"})
    cerca = db.execute("SELECT * FROM recetas WHERE tipo = 'Lentes cerca' ORDER BY id DESC").fetchone()
    assert (cerca["od_esfera"], cerca["oi_esfera"]) == ("+1,50", "0,00")
    # texto que no es un número: se avisa y no se inventa
    r = client.post(f"/clientes/{cid}/recetas/nueva", data={
        "tipo": "Lentes lejos", "od_esfera": "ver informe", "od_adicion": "+2,00", "generar_cerca": "1"}, follow_redirects=True)
    assert "Revisa la esfera de OD" in r.get_data(as_text=True)



def test_receta_de_cerca_solo_desde_lentes_lejos(client, db):
    cid = crear_cliente(client)
    for tipo in ["Lentes multifocales", "Lentes bifocales", "Lentes cerca", "Lentes de contacto"]:
        client.post(f"/clientes/{cid}/recetas/nueva", data={
            "tipo": tipo, "od_esfera": "-1,00", "od_adicion": "+2,00", "generar_cerca": "1"})
    assert db.execute("SELECT COUNT(*) FROM recetas").fetchone()[0] == 4  # ninguna de cerca extra
    assert db.execute("SELECT COUNT(*) FROM recetas WHERE tipo = 'Lentes cerca'").fetchone()[0] == 1


def test_lejos_y_cerca_quedan_como_actuales(client, db):
    cid = crear_cliente(client)
    client.post(f"/clientes/{cid}/recetas/nueva", data={"fecha": "2025-01-10", "tipo": "Lentes lejos", "od_esfera": "-0,50"})
    client.post(f"/clientes/{cid}/recetas/nueva", data={
        "fecha": "2026-09-20", "tipo": "Lentes lejos", "od_esfera": "-1,00", "od_adicion": "+2,00", "generar_cerca": "1"})
    ficha = client.get(f"/clientes/{cid}").get_data(as_text=True)
    recetas = ficha.split('id="recetas"', 1)[1].split('id="compras"', 1)[0]
    assert recetas.count(">Actual</span>") == 2  # lejos y cerca de la última visita, no la de 2025
    assert "Lentes lejos + Lentes cerca" in ficha


def test_armazon_propio_ranurado(client, db):
    propio = db.execute("SELECT id FROM productos WHERE codigo = 'ARMAZON-PROPIO'").fetchone()["id"]
    cid = crear_cliente(client)
    base = {
        "cliente_id": str(cid), "producto_id": [str(propio), ""],
        "descripcion": ["Armazón propio", "Cristales"], "cantidad": ["1", "1"],
        "precio": ["250", "3000"], "descuento": ["0", "0"], "iva": ["22", "22"],
        "medida_calibre": ["52", ""], "medida_puente": ["18", ""], "medida_diagonal": ["", ""],
        "medida_altura": ["", ""], "medida_ranurado": ["1", "1"], "estado": "En taller", "pago": "", "metodo": "Efectivo",
    }
    assert client.post("/ventas/nueva", data=base).status_code == 302
    lineas = db.execute("SELECT ranurado, importe FROM lineas_venta ORDER BY id").fetchall()
    assert tuple(lineas[0]) == ("1", 25000) and lineas[1]["ranurado"] == ""  # solo en el armazón propio
    assert db.execute("SELECT total FROM ventas").fetchone()[0] == 325000
    assert "<b>RANURADO</b>" in client.get("/ventas/1/orden").get_data(as_text=True)

    # desmarcar desde la ficha: la línea vuelve a $ 0 y baja el total
    linea = db.execute("SELECT id FROM lineas_venta ORDER BY id").fetchone()["id"]
    client.post(f"/ventas/1/medidas/{linea}", data={"calibre": "52", "puente": "18"})
    assert tuple(db.execute("SELECT ranurado, precio_unitario, importe FROM lineas_venta WHERE id = ?", (linea,)).fetchone()) == ("", 0, 0)
    assert db.execute("SELECT total FROM ventas").fetchone()[0] == 300000
    assert "RANURADO" not in client.get("/ventas/1/orden").get_data(as_text=True)
    # volver a marcarlo lo sube de nuevo
    client.post(f"/ventas/1/medidas/{linea}", data={"calibre": "52", "ranurado": "1"})
    assert db.execute("SELECT total FROM ventas").fetchone()[0] == 325000


def test_no_se_quita_ranurado_ya_cobrado(client, db):
    propio = db.execute("SELECT id FROM productos WHERE codigo = 'ARMAZON-PROPIO'").fetchone()["id"]
    client.post("/ventas/nueva", data={
        "producto_id": [str(propio)], "descripcion": ["Armazón propio"], "cantidad": ["1"], "precio": ["250"],
        "descuento": ["0"], "iva": ["22"], "medida_calibre": [""], "medida_puente": [""], "medida_diagonal": [""],
        "medida_altura": [""], "medida_ranurado": ["1"], "estado": "En taller", "pago": "250", "metodo": "Efectivo"})
    linea = db.execute("SELECT id FROM lineas_venta").fetchone()["id"]
    r = client.post(f"/ventas/1/medidas/{linea}", data={}, follow_redirects=True)
    assert "No se puede quitar el ranurado" in r.get_data(as_text=True)
    assert db.execute("SELECT ranurado FROM lineas_venta").fetchone()[0] == "1"


def crear_lente(client, codigo="LEN1", descripcion="Monofocal 1.6"):
    r = client.post("/productos/nuevo", data={"codigo": codigo, "categoria": "Cristales",
                                              "descripcion": descripcion, "precio_venta": "3000", "iva": "22"})
    return int(r.headers["Location"].rstrip("/").split("/")[-1])


def venta_varias_recetas(client, cid, recetas, lineas):
    datos = {
        "cliente_id": str(cid), "receta_id": [str(r) for r in recetas],
        "producto_id": [l[0] for l in lineas], "descripcion": [l[1] for l in lineas],
        "cantidad": ["1"] * len(lineas), "precio": ["3000"] * len(lineas),
        "descuento": ["0"] * len(lineas), "iva": ["22"] * len(lineas),
        "linea_receta": [l[2] for l in lineas], "estado": "En taller", "pago": "", "metodo": "Efectivo",
    }
    return client.post("/ventas/nueva", data=datos)


def test_venta_con_lejos_y_cerca(client, db):
    cid = crear_cliente(client)
    client.post(f"/clientes/{cid}/recetas/nueva", data={"fecha": "2026-09-20", "tipo": "Lentes lejos",
                                                        "od_esfera": "-1,00", "od_adicion": "+2,00", "generar_cerca": "1"})
    cerca, lejos = [r["id"] for r in db.execute("SELECT id FROM recetas ORDER BY id")]
    l1, l2 = crear_lente(client, "L1", "Monofocal lejos"), crear_lente(client, "L2", "Monofocal cerca")
    r = venta_varias_recetas(client, cid, [lejos, cerca],
                             [(str(l1), "Monofocal lejos", str(lejos)), (str(l2), "Monofocal cerca", str(cerca)),
                              ("", "Montaje", "")])
    assert r.status_code == 302
    assert [x[0] for x in db.execute("SELECT receta_id FROM venta_recetas ORDER BY orden")] == [lejos, cerca]
    assert db.execute("SELECT receta_id FROM ventas").fetchone()[0] == lejos
    asignadas = [x[0] for x in db.execute("SELECT receta_id FROM lineas_venta ORDER BY id")]
    assert asignadas == [lejos, cerca, None]
    orden = client.get("/ventas/1/orden").get_data(as_text=True)
    assert "Receta · Lentes lejos" in orden and "Receta · Lentes cerca" in orden
    assert "Para: <b>Monofocal cerca</b>" in orden and "+1,00" in orden
    detalle = client.get("/ventas/1").get_data(as_text=True)
    assert detalle.count("Receta utilizada") == 2 and "Receta: Lentes lejos" in detalle
    # no se puede borrar una receta usada como segunda receta de una venta
    client.post(f"/clientes/{cid}/recetas/{cerca}/eliminar")
    assert db.execute("SELECT COUNT(*) FROM recetas").fetchone()[0] == 2


def test_varias_recetas_exige_elegir_en_cada_lente(client, db):
    cid = crear_cliente(client)
    client.post(f"/clientes/{cid}/recetas/nueva", data={"tipo": "Lentes lejos"})
    client.post(f"/clientes/{cid}/recetas/nueva", data={"tipo": "Lentes cerca"})
    l1 = crear_lente(client)
    r = venta_varias_recetas(client, cid, [1, 2], [(str(l1), "Monofocal 1.6", "")])
    assert r.status_code == 200 and "Elige a qué receta corresponde" in r.get_data(as_text=True)
    # una receta que no está entre las de la venta tampoco vale
    client.post(f"/clientes/{cid}/recetas/nueva", data={"tipo": "Lentes de contacto"})
    r = venta_varias_recetas(client, cid, [1, 2], [(str(l1), "Monofocal 1.6", "3")])
    assert r.status_code == 200
    assert db.execute("SELECT COUNT(*) FROM ventas").fetchone()[0] == 0
    # con una sola receta, la lente se le asigna sola
    assert venta_varias_recetas(client, cid, [2], [(str(l1), "Monofocal 1.6", "")]).status_code == 302
    assert db.execute("SELECT receta_id FROM lineas_venta").fetchone()[0] == 2


def test_receta_de_otro_cliente_entre_varias(client, db):
    c1, c2 = crear_cliente(client), crear_cliente(client, nombre="Luis")
    client.post(f"/clientes/{c1}/recetas/nueva", data={"tipo": "Lentes lejos"})
    client.post(f"/clientes/{c2}/recetas/nueva", data={"tipo": "Lentes cerca"})
    r = venta_varias_recetas(client, c1, [1, 2], [("", "Servicio", "")])
    assert r.status_code == 200 and "no pertenece" in r.get_data(as_text=True)


def test_numero_de_trabajo_por_receta(client, db):
    cid = crear_cliente(client)
    client.post(f"/clientes/{cid}/recetas/nueva", data={"tipo": "Lentes lejos", "od_esfera": "-1,00",
                                                        "od_adicion": "+2,00", "generar_cerca": "1"})
    cerca, lejos = [r["id"] for r in db.execute("SELECT id FROM recetas ORDER BY id")]
    l1 = crear_lente(client)
    datos = {"lugar": "laboratorio", "laboratorio": "Vidaltec"}
    venta_varias_recetas(client, cid, [lejos, cerca], [(str(l1), "Lejos", str(lejos)), (str(l1), "Cerca", str(cerca))])
    client.post("/ventas/1/estado", data={"estado": "En taller", **datos})
    inicio = client.get("/").get_data(as_text=True)
    assert "¿A qué receta corresponde?" in inicio and "+ Nº de trabajo" in inicio

    # sin elegir receta no se guarda
    r = client.post("/ventas/1/numero-trabajo", data={"numero_trabajo": "111"}, follow_redirects=True)
    assert "Elige a qué receta corresponde" in r.get_data(as_text=True)
    # número de la receta de lejos: el pulsador sigue para la de cerca
    client.post("/ventas/1/numero-trabajo", data={"numero_trabajo": "VT-100", "receta_id": str(lejos)})
    inicio = client.get("/").get_data(as_text=True)
    assert "Nº VT-100 · Lentes lejos" in inicio and "+ Nº de trabajo" in inicio
    formulario = inicio.split('id="trabajo-1"', 1)[1].split("</form>", 1)[0]
    assert "Lentes cerca" in formulario and "Lentes lejos" not in formulario  # solo la que falta
    # número de la de cerca: ya no hay pulsador
    client.post("/ventas/1/numero-trabajo", data={"numero_trabajo": "VT-101", "receta_id": str(cerca)})
    inicio = client.get("/").get_data(as_text=True)
    assert "+ Nº de trabajo" not in inicio and "Nº VT-101 · Lentes cerca" in inicio

    ficha = client.get(f"/clientes/{cid}").get_data(as_text=True)
    assert "Nº de trabajo Lentes lejos: VT-100" in ficha and "Nº de trabajo Lentes cerca: VT-101" in ficha
    # corregir uno desde la ficha de la venta
    detalle = client.get("/ventas/1").get_data(as_text=True)
    assert f'name="numero_trabajo_{lejos}"' in detalle
    client.post("/ventas/1/estado", data={"estado": "En taller", **datos, f"numero_trabajo_{lejos}": "VT-200",
                                          f"numero_trabajo_{cerca}": "VT-101"})
    assert db.execute("SELECT numero_trabajo FROM venta_recetas WHERE receta_id = ?", (lejos,)).fetchone()[0] == "VT-200"



def test_orden_muestra_cada_receta_una_sola_vez(client, db):
    cid = crear_cliente(client)
    client.post(f"/clientes/{cid}/recetas/nueva", data={"tipo": "Lentes lejos", "od_esfera": "-1,00",
                                                        "od_adicion": "+2,00", "generar_cerca": "1"})
    cerca, lejos = [r["id"] for r in db.execute("SELECT id FROM recetas ORDER BY id")]
    l1 = crear_lente(client)
    venta_varias_recetas(client, cid, [lejos, cerca, lejos],
                         [(str(l1), "Lente lejos OD", str(lejos)), (str(l1), "Lente lejos OI", str(lejos)),
                          (str(l1), "Lente cerca", str(cerca))])
    orden = client.get("/ventas/1/orden").get_data(as_text=True)
    assert orden.count("Receta · Lentes lejos") == 1 and orden.count("Receta · Lentes cerca") == 1
    assert orden.count('<table class="graduacion">') == 2
    assert "Para: <b>Lente lejos OD, Lente lejos OI</b>" in orden and "Para: <b>Lente cerca</b>" in orden
    assert "Receta: <b>" not in orden  # ya no se repite debajo de cada producto


def test_migracion_gafas_a_lentes(tmp_path):
    ruta = str(tmp_path / "vieja.db")
    create_app({"DATABASE": ruta})
    conn = connect(ruta)
    conn.execute("INSERT INTO clientes (nombre) VALUES ('Ana')")
    conn.execute("INSERT INTO recetas (cliente_id, fecha, tipo) VALUES (1, '2026-01-01', 'Gafas progresivas')")
    conn.execute("INSERT INTO recetas (cliente_id, fecha, tipo) VALUES (1, '2026-01-01', 'Lentes de contacto')")
    conn.execute("INSERT INTO productos (codigo, categoria) VALUES ('S1', 'Gafa de sol')")
    conn.commit()
    create_app({"DATABASE": ruta})
    assert [r[0] for r in conn.execute("SELECT tipo FROM recetas ORDER BY id")] == ["Lentes multifocales", "Lentes de contacto"]
    assert conn.execute("SELECT categoria FROM productos WHERE codigo = 'S1'").fetchone()[0] == "Lentes de sol"
    conn.close()


def test_sin_gafas_ni_impuestos_en_pantalla(client, db):
    cid = crear_cliente(client)
    client.post(f"/clientes/{cid}/recetas/nueva", data={"tipo": "Lentes lejos", "od_esfera": "-1,00"})
    pid = crear_producto(client, precio_coste="40", precio_venta="120")
    vender(client, [{"producto_id": str(pid), "precio": "120"}], cliente_id=str(cid), receta_id="1", pago="120")
    import re
    for url in ["/", "/productos/nuevo", f"/productos/{pid}", "/ventas/nueva", "/ventas/1", "/ventas/1/ticket",
                "/ventas/1/orden", f"/clientes/{cid}", f"/clientes/{cid}/recetas/nueva", "/informes", "/caja"]:
        html = client.get(url).get_data(as_text=True)
        texto = re.sub(r"<[^>]+>", " ", html)
        assert not re.search(r"(?i)\bgafas?\b|\biva\b|impuesto|cuota", texto), url
    detalle = client.get(f"/productos/{pid}").get_data(as_text=True)
    assert "$ 80,00" in detalle and "66.7 % del precio de venta" in detalle  # margen = 120 - 40
    csv = client.get("/productos/exportar.csv").get_data(as_text=True)
    assert "IVA" not in csv



def test_migracion_multifocales_y_cristales(tmp_path):
    ruta = str(tmp_path / "vieja.db")
    create_app({"DATABASE": ruta})
    conn = connect(ruta)
    conn.execute("INSERT INTO clientes (nombre) VALUES ('Ana')")
    conn.execute("INSERT INTO recetas (cliente_id, fecha, tipo) VALUES (1, '2026-01-01', 'Gafas progresivas')")
    conn.execute("INSERT INTO recetas (cliente_id, fecha, tipo) VALUES (1, '2026-01-02', 'Lentes progresivas')")
    conn.execute("INSERT INTO productos (codigo, categoria) VALUES ('L1', 'Lente oftálmica')")
    conn.commit()
    create_app({"DATABASE": ruta})
    assert {r[0] for r in conn.execute("SELECT tipo FROM recetas")} == {"Lentes multifocales"}
    assert conn.execute("SELECT categoria FROM productos WHERE codigo = 'L1'").fetchone()[0] == "Cristales"
    conn.close()


def test_sin_progresivas_ni_lente_oftalmica_en_pantalla(client):
    import re
    for url in ["/productos/nuevo", "/productos/", "/ventas/nueva", "/clientes/nuevo"]:
        texto = re.sub(r"<[^>]+>", " ", client.get(url).get_data(as_text=True))
        assert not re.search(r"(?i)progresiv|oftálmic", texto), url
    cid = crear_cliente(client)
    formulario = client.get(f"/clientes/{cid}/recetas/nueva").get_data(as_text=True)
    assert "Lentes multifocales" in formulario and "progresiv" not in formulario.lower()
    assert ">Cristales<" in client.get("/productos/nuevo").get_data(as_text=True)


def test_cierre_del_dia(client, db):
    vender(client, [{"descripcion": "Lentes", "precio": "5000"}], pago=["2000", "1000"], metodo=["Efectivo", "Tarjeta"],
           estado="En taller")
    vender(client, [{"descripcion": "Líquido", "precio": "300"}], pago="300", metodo="Efectivo")
    caja = client.get("/caja").get_data(as_text=True)
    assert "Cerrar el día" in caja
    pagina = client.get("/cierre").get_data(as_text=True)
    assert "$ 5.300,00" in pagina  # ventas del día
    assert "$ 3.300,00" in pagina  # total cobrado
    assert "$ 2.000,00" in pagina  # pendiente de cobro
    assert "$ 2.300,00" in pagina  # efectivo según el programa

    r = client.post("/cierre", data={"efectivo_contado": "2.250", "notas": "Faltan 50 de cambio"}, follow_redirects=True)
    html = r.get_data(as_text=True)
    assert "cerrado" in html and "-$ 50,00" in html and "(falta)" in html
    cierre = db.execute("SELECT * FROM cierres").fetchone()
    assert (cierre["total_ventas"], cierre["total_cobrado"], cierre["efectivo_contado"]) == (530000, 330000, 225000)
    assert "✔ Día cerrado" in client.get("/caja").get_data(as_text=True)

    # un cobro después del cierre: el cierre queda desactualizado hasta volver a cerrar
    client.post("/ventas/1/pago", data={"importe": "2000", "metodo": "Efectivo"})
    assert "Vuelve a cerrar el día" in client.get("/cierre").get_data(as_text=True)
    client.post("/cierre", data={"efectivo_contado": "4.300"})
    assert db.execute("SELECT COUNT(*) FROM cierres").fetchone()[0] == 1
    html = client.get("/cierre").get_data(as_text=True)
    assert "Vuelve a cerrar" not in html and "cuadra" in html


def test_cierre_de_otro_dia_y_sin_efectivo(client, db):
    r = client.post("/cierre", data={"dia": "2026-01-15", "efectivo_contado": ""}, follow_redirects=True)
    assert r.status_code == 200
    fila = db.execute("SELECT dia, efectivo_contado, total_cobrado FROM cierres").fetchone()
    assert tuple(fila) == ("2026-01-15", None, 0)
    assert "15/01/2026" in client.get("/caja").get_data(as_text=True)  # en «Últimos cierres»
    r = client.post("/cierre", data={"efectivo_contado": "abc"}, follow_redirects=True)
    assert "no válido" in r.get_data(as_text=True)
