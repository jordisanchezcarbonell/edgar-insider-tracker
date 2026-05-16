"""Configuración central del proyecto.

Concentramos aquí las constantes que afectan a la ingesta para no esparcirlas
por el código. Cuando crezca, esto se moverá a un fichero de settings o a
variables de entorno; por ahora un módulo Python es lo más simple.
"""

from pathlib import Path

# La SEC exige un User-Agent identificable (nombre + email de contacto). Si lo
# omites o pones algo genérico tipo "python-requests/x", devuelve 403.
USER_AGENT = "Jordi Sanchez jordigw@gmail.com"

# Límite oficial de la SEC: 10 req/s. Vamos a la mitad para tener holgura ante
# microbursts y latencia de red.
RATE_LIMIT_SLEEP_SECONDS = 0.2

# CIK = Central Index Key. Es el identificador permanente que asigna la SEC a
# cada filer; siempre se usa con padding a 10 dígitos en las URLs de data.sec.gov.
# El ticker puede cambiar (rebranding, fusiones); el CIK no.
TARGET_CIKS: dict[str, str] = {
    "AAPL": "0000320193",
    "MSFT": "0000789019",
    "NVDA": "0001045810",
    "TSLA": "0001318605",
    "META": "0001326801",
}

# Cuántos Forms 4 recientes bajamos por empresa. 20 × 5 = 100 filings es
# suficiente para iterar rápido mientras desarrollamos el pipeline.
MAX_FILINGS_PER_COMPANY = 20

# Raíz del proyecto: subimos dos niveles desde src/edgar_insider/config.py.
# Usamos rutas absolutas para que el script funcione igual desde cualquier cwd.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw" / "form4"
