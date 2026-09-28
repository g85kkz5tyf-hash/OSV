"""Envío de SMS a clientes (aviso de «listo para recoger») a través de Twilio."""
import base64
import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request

MENSAJE_POR_DEFECTO = (
    "Hola {nombre}, tu pedido de {optica} ya está listo para retirar. ¡Te esperamos!"
)


class ErrorSMS(Exception):
    pass


def configurado(config):
    return all(config.get(c) for c in ("sms_sid", "sms_token", "sms_remitente"))


def normalizar_telefono(telefono):
    """Pasa un teléfono uruguayo al formato internacional: '099 123 456' -> '+59899123456'."""
    t = re.sub(r"[^\d+]", "", telefono or "")
    if t.startswith("+"):
        return t
    if t.startswith("00"):
        return "+" + t[2:]
    if t.startswith("598") and len(t) >= 11:
        return "+" + t
    if t.startswith("0"):
        t = t[1:]
    if len(t) == 8:  # celular sin el 0 (99 123 456) o fijo (2xxx xxxx)
        return "+598" + t
    raise ErrorSMS(f"el teléfono «{telefono}» no parece un número válido")


def componer_mensaje(config, cliente, venta, saldo):
    plantilla = config.get("sms_mensaje") or MENSAJE_POR_DEFECTO
    valores = {
        "nombre": (cliente["nombre"] or "").strip(),
        "optica": config.get("nombre") or "la óptica",
        "numero": venta["numero"],
        "saldo": saldo,
        "telefono": config.get("telefono") or "",
    }
    try:
        return plantilla.format(**valores).strip()
    except (KeyError, IndexError, ValueError):
        # Llaves mal escritas en el mensaje personalizado: se envía tal cual
        return plantilla.strip()


def _contexto_ssl():
    try:
        from pip._vendor import certifi
    except ImportError:
        try:
            import certifi
        except ImportError:
            return None
    return ssl.create_default_context(cafile=certifi.where())


def _enviar_peticion(peticion):
    try:
        with urllib.request.urlopen(peticion, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.URLError as e:
        # En los Mac, Python no trae certificados: se usan los de pip
        if isinstance(getattr(e, "reason", None), ssl.SSLError) and _contexto_ssl():
            with urllib.request.urlopen(peticion, timeout=15, context=_contexto_ssl()) as r:
                return json.loads(r.read())
        raise


def enviar(config, telefono, mensaje):
    """Envía el SMS. Devuelve el número al que se envió o lanza ErrorSMS con el motivo."""
    if not configurado(config):
        raise ErrorSMS("el envío de SMS no está configurado (ver Configuración)")
    destino = normalizar_telefono(telefono)
    sid, token = config["sms_sid"].strip(), config["sms_token"].strip()
    datos = urllib.parse.urlencode({
        "To": destino, "From": config["sms_remitente"].strip(), "Body": mensaje,
    }).encode()
    peticion = urllib.request.Request(
        f"https://api.twilio.com/2010-04-01/Accounts/{urllib.parse.quote(sid)}/Messages.json",
        data=datos,
        headers={"Authorization": "Basic " + base64.b64encode(f"{sid}:{token}".encode()).decode()},
    )
    try:
        _enviar_peticion(peticion)
    except urllib.error.HTTPError as e:
        try:
            detalle = json.loads(e.read()).get("message", "")
        except Exception:
            detalle = ""
        raise ErrorSMS(f"el servicio de SMS lo rechazó ({e.code}) {detalle}".strip())
    except (urllib.error.URLError, OSError) as e:
        raise ErrorSMS(f"no se pudo conectar con el servicio de SMS ({e})")
    return destino
