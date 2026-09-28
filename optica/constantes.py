CATEGORIA_ARMAZON = "Armazón"

CATEGORIAS = [
    CATEGORIA_ARMAZON,
    "Gafa de sol",
    "Lente oftálmica",
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

METODOS_PAGO = ["Efectivo", "Tarjeta", "Transferencia", "Financiado"]

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
