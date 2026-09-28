-- Esquema de la base de datos de la óptica.
-- Los importes se guardan en céntimos (enteros) para evitar errores de redondeo.

CREATE TABLE IF NOT EXISTS clientes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    apellidos TEXT NOT NULL DEFAULT '',
    dni TEXT NOT NULL DEFAULT '',
    fecha_nacimiento TEXT NOT NULL DEFAULT '',
    telefono TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    direccion TEXT NOT NULL DEFAULT '',
    localidad TEXT NOT NULL DEFAULT '',
    codigo_postal TEXT NOT NULL DEFAULT '',
    notas TEXT NOT NULL DEFAULT '',
    acepta_comunicaciones INTEGER NOT NULL DEFAULT 0,
    creado TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS recetas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
    fecha TEXT NOT NULL,
    tipo TEXT NOT NULL DEFAULT 'Gafas lejos',
    optometrista TEXT NOT NULL DEFAULT '',
    -- Ojo derecho
    od_esfera TEXT NOT NULL DEFAULT '',
    od_cilindro TEXT NOT NULL DEFAULT '',
    od_eje TEXT NOT NULL DEFAULT '',
    od_adicion TEXT NOT NULL DEFAULT '',
    od_prisma TEXT NOT NULL DEFAULT '',
    od_av TEXT NOT NULL DEFAULT '',
    od_dnp TEXT NOT NULL DEFAULT '',
    od_altura TEXT NOT NULL DEFAULT '',
    -- Ojo izquierdo
    oi_esfera TEXT NOT NULL DEFAULT '',
    oi_cilindro TEXT NOT NULL DEFAULT '',
    oi_eje TEXT NOT NULL DEFAULT '',
    oi_adicion TEXT NOT NULL DEFAULT '',
    oi_prisma TEXT NOT NULL DEFAULT '',
    oi_av TEXT NOT NULL DEFAULT '',
    oi_dnp TEXT NOT NULL DEFAULT '',
    oi_altura TEXT NOT NULL DEFAULT '',
    -- Lentes de contacto
    lc_marca TEXT NOT NULL DEFAULT '',
    lc_curva_base TEXT NOT NULL DEFAULT '',
    lc_diametro TEXT NOT NULL DEFAULT '',
    -- Otros datos
    presion_intraocular TEXT NOT NULL DEFAULT '',
    observaciones TEXT NOT NULL DEFAULT '',
    proxima_revision TEXT NOT NULL DEFAULT '',
    creado TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS productos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT NOT NULL UNIQUE,
    categoria TEXT NOT NULL,
    marca TEXT NOT NULL DEFAULT '',
    modelo TEXT NOT NULL DEFAULT '',
    color TEXT NOT NULL DEFAULT '',
    calibre TEXT NOT NULL DEFAULT '',
    puente TEXT NOT NULL DEFAULT '',
    diagonal TEXT NOT NULL DEFAULT '',
    altura TEXT NOT NULL DEFAULT '',
    descripcion TEXT NOT NULL DEFAULT '',
    proveedor TEXT NOT NULL DEFAULT '',
    precio_coste INTEGER NOT NULL DEFAULT 0,
    precio_venta INTEGER NOT NULL DEFAULT 0,
    iva INTEGER NOT NULL DEFAULT 22,
    stock INTEGER NOT NULL DEFAULT 0,
    stock_minimo INTEGER NOT NULL DEFAULT 0,
    controla_stock INTEGER NOT NULL DEFAULT 1,
    activo INTEGER NOT NULL DEFAULT 1,
    creado TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS movimientos_stock (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    producto_id INTEGER NOT NULL REFERENCES productos(id),
    fecha TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    tipo TEXT NOT NULL,          -- entrada, ajuste, venta, anulacion
    cantidad INTEGER NOT NULL,   -- positiva suma, negativa resta
    stock_resultante INTEGER NOT NULL,
    motivo TEXT NOT NULL DEFAULT '',
    venta_id INTEGER REFERENCES ventas(id)
);

CREATE TABLE IF NOT EXISTS ventas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero TEXT NOT NULL UNIQUE,
    fecha TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    cliente_id INTEGER REFERENCES clientes(id),
    receta_id INTEGER REFERENCES recetas(id),
    total INTEGER NOT NULL DEFAULT 0,
    estado TEXT NOT NULL DEFAULT 'Entregado', -- Pendiente, En taller, Listo para recoger, Entregado, Anulada
    ejecucion TEXT NOT NULL DEFAULT '', -- «Taller propio» o el nombre del laboratorio
    numero_trabajo TEXT NOT NULL DEFAULT '', -- número que da el laboratorio al trabajo
    fecha_entrega_prevista TEXT NOT NULL DEFAULT '',
    notas TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS lineas_venta (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    venta_id INTEGER NOT NULL REFERENCES ventas(id) ON DELETE CASCADE,
    producto_id INTEGER REFERENCES productos(id),
    descripcion TEXT NOT NULL,
    cantidad INTEGER NOT NULL,
    precio_unitario INTEGER NOT NULL,
    descuento_pct INTEGER NOT NULL DEFAULT 0,
    iva INTEGER NOT NULL DEFAULT 22,
    importe INTEGER NOT NULL,
    -- Medidas del armazón que trae el cliente (solo en la línea «Armazón propio»)
    calibre TEXT NOT NULL DEFAULT '',
    puente TEXT NOT NULL DEFAULT '',
    diagonal TEXT NOT NULL DEFAULT '',
    altura TEXT NOT NULL DEFAULT '',
    ranurado TEXT NOT NULL DEFAULT '', -- '1' si el armazón propio va ranurado
    receta_id INTEGER REFERENCES recetas(id) -- receta a la que corresponde la lente
);

CREATE TABLE IF NOT EXISTS pagos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    venta_id INTEGER NOT NULL REFERENCES ventas(id) ON DELETE CASCADE,
    fecha TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    importe INTEGER NOT NULL,
    metodo TEXT NOT NULL DEFAULT 'Efectivo'
);

CREATE INDEX IF NOT EXISTS idx_recetas_cliente ON recetas(cliente_id);
CREATE INDEX IF NOT EXISTS idx_ventas_cliente ON ventas(cliente_id);
CREATE INDEX IF NOT EXISTS idx_ventas_fecha ON ventas(fecha);
CREATE INDEX IF NOT EXISTS idx_lineas_venta ON lineas_venta(venta_id);
CREATE INDEX IF NOT EXISTS idx_pagos_venta ON pagos(venta_id);
CREATE INDEX IF NOT EXISTS idx_movimientos_producto ON movimientos_stock(producto_id);

CREATE TABLE IF NOT EXISTS configuracion (
    clave TEXT PRIMARY KEY,
    valor TEXT NOT NULL DEFAULT ''
);

-- Compras hechas antes de usar el programa: solo informativas. No afectan a ventas,
-- cobros, caja, stock ni informes.
CREATE TABLE IF NOT EXISTS compras_anteriores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
    fecha TEXT NOT NULL DEFAULT '',
    descripcion TEXT NOT NULL,
    importe INTEGER,
    observaciones TEXT NOT NULL DEFAULT '',
    creado TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_compras_anteriores_cliente ON compras_anteriores(cliente_id);

-- Recetas asociadas a una venta (p. ej. lejos y cerca a la vez). ventas.receta_id es la primera.
CREATE TABLE IF NOT EXISTS venta_recetas (
    venta_id INTEGER NOT NULL REFERENCES ventas(id) ON DELETE CASCADE,
    receta_id INTEGER NOT NULL REFERENCES recetas(id),
    orden INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (venta_id, receta_id)
);
