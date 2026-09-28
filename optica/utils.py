from decimal import ROUND_HALF_UP, Decimal, InvalidOperation


def parse_importe(texto, defecto=0):
    """Convierte '12,50', '12.50' o '1.234,56' a céntimos (int)."""
    texto = (texto or "").strip().replace("€", "").replace(" ", "")
    if not texto:
        return defecto
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        valor = Decimal(texto)
    except InvalidOperation:
        raise ValueError(f"Importe no válido: {texto}")
    return int((valor * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def parse_entero(texto, defecto=0):
    texto = (texto or "").strip()
    if not texto:
        return defecto
    try:
        return int(texto)
    except ValueError:
        raise ValueError(f"Número no válido: {texto}")


def formato_euros(centimos):
    centimos = int(centimos or 0)
    signo = "-" if centimos < 0 else ""
    euros, cent = divmod(abs(centimos), 100)
    miles = f"{euros:,}".replace(",", ".")
    return f"{signo}{miles},{cent:02d} €"


def formato_importe(centimos):
    """Formato para rellenar campos de formulario (sin símbolo ni separador de miles)."""
    centimos = int(centimos or 0)
    signo = "-" if centimos < 0 else ""
    euros, cent = divmod(abs(centimos), 100)
    return f"{signo}{euros},{cent:02d}"


def importe_linea(cantidad, precio_unitario, descuento_pct):
    bruto = Decimal(cantidad) * Decimal(precio_unitario)
    neto = bruto * (Decimal(100) - Decimal(descuento_pct)) / Decimal(100)
    return int(neto.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def desglose_iva(lineas):
    """Agrupa importes (IVA incluido) por tipo de IVA: [(iva, base, cuota, total)]."""
    totales = {}
    for linea in lineas:
        totales[linea["iva"]] = totales.get(linea["iva"], 0) + linea["importe"]
    resultado = []
    for iva, total in sorted(totales.items()):
        base = int((Decimal(total) * 100 / (100 + iva)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        resultado.append((iva, base, total - base, total))
    return resultado


def formato_fecha(texto):
    """'2026-09-28' o '2026-09-28 10:30:00' -> '28/09/2026' (con hora si la hay)."""
    if not texto:
        return ""
    fecha, _, hora = texto.partition(" ")
    partes = fecha.split("-")
    if len(partes) != 3:
        return texto
    salida = f"{partes[2]}/{partes[1]}/{partes[0]}"
    if hora:
        salida += " " + hora[:5]
    return salida
