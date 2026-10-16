"""Configuración central: URLs de servicios, rutas y parámetros."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATOS_DIR = Path(os.getenv("UBI_DATOS_DIR", BASE_DIR / "datos"))

# Sistema de referencia de trabajo: ETRS89 / UTM 31N (metros), el de la Generalitat.
EPSG_UTM = 25831
EPSG_WGS84 = 4326

HTTP_TIMEOUT = float(os.getenv("UBI_HTTP_TIMEOUT", "25"))
USER_AGENT = os.getenv("UBI_USER_AGENT", "PlataformaUbicaciones/0.1 (informes de idoneidad)")

# --- Catastro ---
CATASTRO_COORD = "https://ovc.catastro.meh.es/OVCServWeb/OVCWcfCallejero/COVCCoordenadas.svc/json"
CATASTRO_CALLEJERO = "https://ovc.catastro.meh.es/OVCServWeb/OVCWcfCallejero/COVCCallejero.svc/json"
CATASTRO_WFS_CP = "https://ovc.catastro.meh.es/INSPIRE/wfsCP.aspx"
CATASTRO_WMS = "https://ovc.catastro.meh.es/cartografia/INSPIRE/spadgcwms.aspx"
CATASTRO_FICHA = "https://www1.sedecatastro.gob.es/CYCBienInmueble/OVCConCiud.aspx?RefC={rc}"

# --- Generalitat (Hipermapa): un único WFS para urbanismo, agua y tráfico ---
GENCAT_WFS = "https://sig.gencat.cat/ows/wfs"
CAPA_MUC_QUALIF = "PLANEJAMENT:MUC_QUALIFICACIONS"
CAPA_MUC_CLASSIF = "PLANEJAMENT:MUC_CLASSIFICACIONS"
CAPA_MUC_SECTOR = "PLANEJAMENT:MUC_SECTOR_DESENVOLUPAMENT"
CAPA_MUC_PDERIVAT = "PLANEJAMENT:MUC_PDERIVAT_QUALIFICACIO"
CAPA_PLA_GENERAL = "PLANEJAMENT:PLANEJAMENT_GENERAL_VIGENT"
CAPA_ZFP = "AIGUA:AIGUA_ZFP"
CAPA_LI10 = "AIGUA:AIGUA_LI10"
CAPA_LI100 = "AIGUA:AIGUA_LI100"
CAPA_LI500 = "AIGUA:AIGUA_LI500"
CAPA_DPH = "AIGUA:AIGUA_DPH"
# Nota: la capa XT_VIARI_IMD_2023 existe pero está vacía (comprobado 16/10/2026).
CAPAS_IMD = ["XARXES_TRANSPORT:XT_VIARI_IMD_2023", "XARXES_TRANSPORT:XT_VIARI_IMD_2022"]

# --- Inundabilidad estatal (SNCZI vía IDEE, cubre toda España, incluida la cuenca del Ebro) ---
IDEE_INUNDACIONES_WMS = "https://servicios.idee.es/wms-inspire/riesgos-naturales/inundaciones"
SNCZI_CAPAS = {
    "T10": "NZ.Flood.FluvialT10",
    "T100": "NZ.Flood.FluvialT100",
    "T500": "NZ.Flood.FluvialT500",
    "MarinaT100": "NZ.Flood.MarinaT100",
    "MarinaT500": "NZ.Flood.MarinaT500",
}

# --- ICGC ---
ICGC_GEOCODER = "https://eines.icgc.cat/geocodificador"
ICGC_ORTO_WMS = "https://geoserveis.icgc.cat/servei/catalunya/orto-territorial/wms"
# Tira histórica: vuelo de 1956-57, 1998, 2015 y la vigente.
ORTOS_HISTORICAS = [
    ("1956-57", "ortofoto_blanc_i_negre_1956-1957"),
    ("1998", "ortofoto_blanc_i_negre_1998"),
    ("2015", "ortofoto_color_2015"),
    ("Actual", "ortofoto_color_vigent"),
]

# --- Entorno, gasolineras, población ---
OVERPASS_URL = os.getenv("UBI_OVERPASS_URL", "https://overpass-api.de/api/interpreter")
CARBURANTES_URL = (
    "https://sedeaplicaciones.minetur.gob.es/ServiciosRESTCarburantes/PreciosCarburantes/"
    "EstacionesTerrestres/FiltroProvincia/{prov}"
)
IDESCAT_EMEX = "https://api.idescat.cat/emex/v1/dades.json"

# --- Resumen IA (opcional) ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("UBI_MODELO_IA", "claude-sonnet-5-5")

# --- Ficheros locales (descargas periódicas) ---
FICHERO_AFOROS = DATOS_DIR / "aforos.csv"          # IMD 2025 Generalitat, 2024 Estado, etc.
FICHERO_RED = DATOS_DIR / "capacidad_red.csv"      # Capacidad de acceso de distribuidoras
FICHERO_SUELO = DATOS_DIR / "precio_suelo.csv"     # Precio del suelo urbano por municipio

RADIOS_ENTORNO = [500, 1000, 2000]
RADIOS_TRAFICO = [500, 1000]
