CATEGORIA_ARMAZON = "Armazón"
CATEGORIA_LENTE = "Lente oftálmica"

CATEGORIAS = [
    CATEGORIA_ARMAZON,
    "Gafa de sol",
    CATEGORIA_LENTE,
    "Lente de contacto",
    "Líquido / mantenimiento",
    "Accesorio",
    "Servicio",
]

# IVA de Uruguay: tasa básica, tasa mínima y exento
TIPOS_IVA = [22, 10, 0]

TIPOS_RECETA = [
    "Gafas lejos",
    "Gafas cerca",
    "Gafas progresivas",
    "Gafas bifocales",
    "Gafas ocupacionales",
    "Lentes de contacto",
]

ESTADOS_VENTA = ["Pendiente", "En taller", "Listo para recoger", "Entregado", "Anulada"]
ESTADOS_ABIERTOS = ["Pendiente", "En taller", "Listo para recoger"]

METODOS_PAGO = ["Efectivo", "Tarjeta", "Transferencia", "Financiado", "Prestación"]

CAMPOS_OJO = [
    ("esfera", "Esfera"),
    ("cilindro", "Cilindro"),
    ("eje", "Eje"),
    ("adicion", "Adición"),
    ("prisma", "Prisma"),
    ("av", "AV"),
    ("dnp", "DNP"),
    ("altura", "Altura"),
]

# Medidas del armazón: (campo, nombre, inicial que se imprime en la orden de trabajo)
MEDIDAS_ARMAZON = [
    ("calibre", "Calibre", "C"),
    ("puente", "Puente", "P"),
    ("diagonal", "Diagonal", "D"),
    ("altura", "Altura", "A"),
]

# Dónde se hace el trabajo y color del recuadro de la orden de trabajo
TALLER_PROPIO = "Taller propio"
LABORATORIOS = ["Vidaltec", "Camponac", "Rodenstock", "Jiki"]
COLORES_EJECUCION = {
    TALLER_PROPIO: "#e10600",  # rojo
    "Vidaltec": "#1e9e3a",     # verde
    "Camponac": "#38bdf8",     # celeste
    "Rodenstock": "#1d4ed8",   # azul
    "Jiki": "#7e22ce",         # púrpura
}

# Producto especial para cuando el cliente trae su propio armazón (solo compra cristales)
CODIGO_ARMAZON_PROPIO = "ARMAZON-PROPIO"
PRECIO_RANURADO = 25000  # $ 250 (en centésimos) si el armazón propio va ranurado
