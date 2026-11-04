FROM python:3.12-slim

# Librerías del sistema que necesita WeasyPrint para generar el PDF
RUN apt-get update && apt-get install -y --no-install-recommends \
      libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libharfbuzz-subset0 libffi8 fonts-dejavu-core fonts-inter \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

ENV PORT=8000
EXPOSE 8000
# Al arrancar: si no hay aforos descargados, se bajan del visor de la Generalitat (no bloquea si falla).
CMD sh -c "[ -f datos/aforos.csv ] || python -m scripts.descargar_aforos_gencat || true; uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"
