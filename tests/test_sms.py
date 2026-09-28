import base64
import io
import urllib.error
import urllib.parse

import pytest

from optica import create_app, sms
from optica.db import connect


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


@pytest.fixture
def twilio(monkeypatch):
    """Sustituye a Twilio: guarda las peticiones en vez de enviar SMS reales."""
    enviados = []

    def enviar_peticion(peticion):
        datos = dict(urllib.parse.parse_qsl(peticion.data.decode()))
        enviados.append({"url": peticion.full_url, "auth": peticion.headers["Authorization"], **datos})
        return {"sid": "SM123"}

    monkeypatch.setattr(sms, "_enviar_peticion", enviar_peticion)
    return enviados


def configurar_sms(client, activo="1", mensaje=""):
    client.post("/configuracion", data={
        "seccion": "sms", "sms_activo": activo, "sms_sid": "AC123", "sms_token": "secreto",
        "sms_remitente": "+15550001111", "sms_mensaje": mensaje,
    })


def venta_en_taller(client, telefono="099 123 456"):
    client.post("/clientes/nuevo", data={"nombre": "Ana", "apellidos": "García", "telefono": telefono})
    client.post("/ventas/nueva", data={
        "cliente_id": "1", "descripcion": ["Lentes"], "producto_id": [""], "cantidad": ["1"],
        "precio": ["3000"], "descuento": ["0"], "iva": ["22"], "estado": "En taller",
        "pago": "1000", "metodo": "Efectivo",
    })


@pytest.mark.parametrize("entrada,salida", [
    ("099 123 456", "+59899123456"),
    ("099123456", "+59899123456"),
    ("99123456", "+59899123456"),
    ("+598 99 123 456", "+59899123456"),
    ("59899123456", "+59899123456"),
    ("0059899123456", "+59899123456"),
    ("2901 2345", "+59829012345"),
])
def test_normalizar_telefono(entrada, salida):
    assert sms.normalizar_telefono(entrada) == salida


def test_telefono_invalido():
    with pytest.raises(sms.ErrorSMS):
        sms.normalizar_telefono("123")


def test_sms_al_pasar_a_listo(client, db, twilio):
    configurar_sms(client, mensaje="Hola {nombre}, pedido {numero} listo. Saldo {saldo}")
    venta_en_taller(client)
    r = client.post("/ventas/1/cambiar-estado", data={"estado": "Listo para recoger", "volver": "/"}, follow_redirects=True)
    assert "SMS enviado a Ana" in r.get_data(as_text=True)
    assert len(twilio) == 1
    enviado = twilio[0]
    assert enviado["To"] == "+59899123456" and enviado["From"] == "+15550001111"
    assert enviado["Body"].startswith("Hola Ana, pedido 20") and enviado["Body"].endswith("Saldo $ 2.000,00")
    assert "/Accounts/AC123/Messages.json" in enviado["url"]
    assert base64.b64decode(enviado["auth"].split()[1]) == b"AC123:secreto"
    assert tuple(db.execute("SELECT enviado, telefono FROM avisos").fetchone()) == (1, "+59899123456")

    # volver a «En taller» y otra vez a «Listo» no repite el SMS
    client.post("/ventas/1/cambiar-estado", data={"estado": "En taller"})
    client.post("/ventas/1/estado", data={"estado": "Listo para recoger"})
    assert len(twilio) == 1
    # pero se puede reenviar a mano
    client.post("/ventas/1/avisar")
    assert len(twilio) == 2


def test_sin_activar_no_envia(client, db, twilio):
    configurar_sms(client, activo="")
    venta_en_taller(client)
    client.post("/ventas/1/cambiar-estado", data={"estado": "Listo para recoger"})
    assert twilio == []
    assert "Enviar SMS ahora" in client.get("/ventas/1").get_data(as_text=True)


def test_sin_configurar_lo_indica(client, twilio):
    venta_en_taller(client)
    client.post("/ventas/1/cambiar-estado", data={"estado": "Listo para recoger"})
    assert twilio == []
    assert "no está configurado" in client.get("/ventas/1").get_data(as_text=True)


def test_cliente_sin_telefono(client, twilio):
    configurar_sms(client)
    venta_en_taller(client, telefono="")
    r = client.post("/ventas/1/cambiar-estado", data={"estado": "Listo para recoger"}, follow_redirects=True)
    assert "no tiene un cliente con teléfono" in r.get_data(as_text=True)
    assert twilio == []


def test_error_del_servicio_queda_registrado(client, db, monkeypatch):
    def rechazar(peticion):
        raise urllib.error.HTTPError(peticion.full_url, 401, "Unauthorized", {},
                                     io.BytesIO(b'{"message": "Authenticate"}'))
    monkeypatch.setattr(sms, "_enviar_peticion", rechazar)
    configurar_sms(client)
    venta_en_taller(client)
    r = client.post("/ventas/1/cambiar-estado", data={"estado": "Listo para recoger"}, follow_redirects=True)
    assert "No se pudo enviar el SMS" in r.get_data(as_text=True)
    assert db.execute("SELECT enviado, error FROM avisos").fetchone()[0] == 0
    assert "Authenticate" in client.get("/ventas/1").get_data(as_text=True)


def test_sms_de_prueba_y_secciones_independientes(client, db, twilio):
    client.post("/configuracion", data={"seccion": "tienda", "nombre": "Óptica Sol"})
    configurar_sms(client)
    # guardar los datos de la óptica no borra los del SMS
    client.post("/configuracion", data={"seccion": "tienda", "nombre": "Óptica Sol 2"})
    r = client.post("/configuracion/sms-prueba", data={"telefono": "099123456"}, follow_redirects=True)
    assert "SMS de prueba enviado" in r.get_data(as_text=True)
    assert "Óptica Sol 2" in twilio[0]["Body"]
