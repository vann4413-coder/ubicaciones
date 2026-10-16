# Plataforma de Ubicaciones

Web que genera, para cualquier parcela de Cataluña, un informe de idoneidad con catastro,
urbanismo, cambios de planeamiento, evolución histórica, inundabilidad, red eléctrica,
tráfico y accesos, entorno, valor del suelo, puntuación por perfil y anexo de fuentes.

Todo sale dentro de la web: el usuario no tiene que ir a ninguna otra página.

## Cómo funciona

1. El usuario busca una dirección, una referencia catastral o unas coordenadas, o hace clic en el mapa.
2. La web localiza la parcela catastral y la dibuja.
3. Al pulsar «Generar informe» consulta todas las fuentes en paralelo (30–60 s) y muestra la
   puntuación. El informe completo se puede ver en pantalla o descargar en PDF.

## Fuentes

| Bloque | Fuente | Cómo se obtiene |
|---|---|---|
| Parcela | Catastro (OVC + WFS INSPIRE) | En vivo |
| Urbanismo | MUC, WFS `sig.gencat.cat/ows/wfs` | En vivo |
| Cambios de planeamiento | RPUC (API del portal) | En vivo |
| Evolución histórica | Ortofotos ICGC 1956-57, 1998, 2015 y actual | En vivo |
| Inundabilidad | ACA (WFS Generalitat) + SNCZI (WMS IDEE) | En vivo |
| Tráfico | Visor GAF de la Generalitat (IMD hasta el último año cerrado) + capa de tramos del WFS | Descarga con script + en vivo |
| Accesos y entorno | OpenStreetMap (Overpass) | En vivo |
| Gasolineras | Geoportal de carburantes | En vivo |
| Población | Idescat | En vivo |
| Red eléctrica | Ficheros de capacidad de las distribuidoras | Carga mensual con script |
| Valor del suelo | Ministerio de Transportes | Carga con script |

## Puesta en marcha en local

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python -m scripts.descargar_aforos_gencat            # IMD de la Generalitat
uvicorn app.main:app --reload
```

Abrir http://localhost:8000

## Publicarla en internet

El proyecto trae un `Dockerfile`. Cualquier servicio que acepte Docker sirve (Render, Railway,
Fly.io, un servidor propio). En Render: «New → Web Service», conectar este repositorio y elegir
Docker; no hace falta nada más. Al arrancar descarga los aforos si no los tiene.

Variables de entorno opcionales:

- `ANTHROPIC_API_KEY`: activa el resumen redactado por IA y la lectura automática de las ortofotos
  históricas. Sin ella, el resumen se genera con reglas y las ortofotos se muestran sin comentario.
- `UBI_DATOS_DIR`: carpeta de los ficheros descargados (por defecto `datos/`). Conviene que sea un
  disco persistente.

## Datos que hay que cargar periódicamente

```bash
# IMD de la Generalitat (una vez al año, cuando publiquen el año cerrado)
python -m scripts.descargar_aforos_gencat

# IMD de la red del Estado u otra tabla de aforos (CSV/XLSX con carretera, PK, IMD...)
python -m scripts.importar_aforos fichero.xlsx --anio 2024 --fuente "Ministerio de Transportes 2024" --organismo Estado

# Capacidad de red (cada mes, fichero de la distribuidora)
python -m scripts.importar_capacidad_red fichero.xlsx --gestor "e-distribución" --fecha 2026-10

# Precio del suelo urbano
python -m scripts.importar_precio_suelo fichero.xlsx
```

## Puntuación

Los pesos por perfil, los tramos de IMD y la potencia objetivo están en `app/analisis/perfiles.py`
y se pueden cambiar sin tocar el resto. Filtros eliminatorios: zona de flujo preferente, calificación
incompatible o solo con plan especial y, para recarga, nudo sin capacidad y sin marca 0*.

## Pruebas

```bash
pytest
```

Las pruebas usan respuestas reales capturadas de Catastro, ICGC, Idescat, RPUC y el visor de aforos,
y capas simuladas con los mismos campos que los servicios. `python -m tests.servidor_demo` arranca la
web con todas las fuentes simuladas, para probar la interfaz sin conexión.

## Estructura

```
app/
  fuentes/      un módulo por fuente de datos
  analisis/     métricas de parcela, compatibilidad, puntuación, resumen, evolución
  informe/      orquestación, mapas, plantilla HTML y PDF
  web/static/   página con mapa y buscador
scripts/        descarga e importación de datos periódicos
tests/          pruebas y respuestas reales de las fuentes
```
