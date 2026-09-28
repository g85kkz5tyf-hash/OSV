# Gestión Óptica

Programa de gestión para una óptica pequeña: **stock**, **clientes** (con ficha, recetas de
optometría e historial de compras) y **ventas** (con encargos, señales y cobros pendientes).

Funciona en tu propio ordenador: se abre en el navegador, no necesita internet ni cuotas, y
todos los datos quedan guardados en un único archivo (`datos/optica.db`).

## Qué incluye

**Clientes**
- Ficha con datos personales, notas y consentimiento de comunicaciones.
- Recetas de optometría: esfera, cilindro, eje, adición, prisma, AV, DNP y altura para cada ojo,
  datos de lentes de contacto, presión intraocular, observaciones y fecha de próxima revisión.
  Se pueden imprimir.
- Historial de compras con lo pendiente de pago.

**Stock**
- Productos por categoría (monturas, gafas de sol, lentes oftálmicas, lentes de contacto,
  líquidos, accesorios, servicios), con precio de coste, PVP e IVA (21 %, 10 %, 4 %, 0 %).
- Entradas de mercancía y ajustes por recuento, con el historial de movimientos.
- Aviso de stock bajo, valor del inventario y exportación a Excel (CSV).
- Productos "por encargo" que no controlan stock (p. ej. lentes graduadas a medida).

**Ventas**
- Venta rápida con buscador de productos y clientes, líneas libres y descuentos por línea.
- Asociación a la receta del cliente.
- Encargos: estados *Pendiente → En taller → Listo para recoger → Entregado* y fecha de
  entrega prevista.
- Cobros parciales (señal + resto) con varias formas de pago.
- Ticket imprimible (factura simplificada con desglose de IVA).
- Anulación: devuelve los artículos al stock y registra la devolución del dinero.

**Además**
- Pantalla de inicio con ventas del día y del mes, encargos en curso, stock bajo y revisiones
  próximas.
- Caja del día por forma de pago.
- Informes anuales por mes, categoría y productos más vendidos.
- Copia de seguridad descargable con un clic.

## Instalación y uso

Instrucciones paso a paso para quien no sabe de informática: [LEEME-INSTALACION.txt](LEEME-INSTALACION.txt).

Necesitas **Python 3.10 o superior** ([descargar](https://www.python.org/downloads/); en Windows,
marca la casilla *"Add Python to PATH"* al instalar).

- **Windows:** doble clic en `iniciar-windows.bat`.
- **Mac:** doble clic en `iniciar-mac.command` (la primera vez: clic derecho → Abrir).

La primera vez tarda un poco porque instala lo necesario. Después se abre el navegador en
<http://127.0.0.1:5000>. Deja abierta la ventana negra mientras uses el programa.

Lo primero es ir a **Configuración** y poner el nombre, NIF y dirección de la óptica, que
aparecerán en los tickets y en las recetas impresas.

### Copias de seguridad

En **Configuración → Descargar copia de seguridad** obtienes un archivo con todos los datos.
Hazlo con regularidad y guárdalo fuera del ordenador. Para restaurarlo, cierra el programa y
sustituye `datos/optica.db` por la copia.

> El programa está pensado para usarse en un único ordenador de la tienda. Contiene datos de
> salud de tus clientes: protege el ordenador con contraseña y guarda las copias en un lugar seguro.

## Para desarrolladores

```sh
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pytest                 # tests
python iniciar.py      # arrancar
```

Estructura: `optica/` contiene la aplicación Flask (`clientes.py`, `productos.py`, `ventas.py`,
`main.py`), el esquema SQLite (`schema.sql`) y las plantillas. Los importes se guardan en
céntimos. La variable de entorno `OPTICA_DB` permite usar otra ruta para la base de datos.
