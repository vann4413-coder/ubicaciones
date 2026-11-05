# ---------- Etapa 1: base local del entorno (OpenStreetMap de Cataluña) ----------
# Descarga el extracto de Geofabrik y deja en /datos_osm los negocios, naves y polígonos industriales.
# Así el informe no depende de los servidores públicos de Overpass. Se refresca en cada despliegue.
FROM python:3.12-slim AS entorno_osm
RUN apt-get update && apt-get install -y --no-install-recommends osmium-tool \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt osmium==4.0.2
COPY app ./app
COPY scripts ./scripts
RUN python -m scripts.preparar_entorno_osm --salida /datos_osm

# ---------- Etapa 2: servidor web ----------
FROM python:3.12-slim

# Librerías del sistema que necesita WeasyPrint para generar el PDF
RUN apt-get update && apt-get install -y --no-install-recommends \
      libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libharfbuzz-subset0 libffi8 fonts-dejavu-core fonts-inter \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
COPY --from=entorno_osm /datos_osm/ ./datos/

ENV PORT=8000
EXPOSE 8000
# Al arrancar: si no hay aforos, se bajan del visor de la Generalitat; la capacidad de red de e-distribución
# se refresca en segundo plano (publica un fichero nuevo cada mes). Nada de esto bloquea si falla.
CMD sh -c "[ -f datos/aforos.csv ] || python -m scripts.descargar_aforos_gencat || true; (timeout 180 python -m scripts.descargar_capacidad_red || true) & uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"
