# edgar-insider-tracker

Pipeline en Python para descargar, parsear y analizar **Forms 3/4/5** (insider trading) de [SEC EDGAR](https://www.sec.gov/edgar.shtml), con una capa de visualización en Streamlit.

No es un proyecto para "predecir el mercado". Es un proyecto de **ingesta y análisis riguroso de datos regulatorios reales**, honesto sobre los límites de lo que estas formas reportan.

## Estado actual: Fase 2 — Parseo de Forms 4

Fase 1 descarga los Forms 4 crudos. Fase 2 los convierte en dataclasses tipadas (`ParsedFiling`, `Transaction`, `Insider`, `Issuer`) y aplana a filas listas para análisis. Cada transacción se categoriza con cuidado (p. ej. distinguir **F**=tax withholding de **S**=open-market sale — confundirlas corrompería cualquier análisis de sentimiento insider).

### Cómo ejecutar

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Fase 1: descarga (idempotente)
python scripts/download_initial_batch.py

# Fase 2: parsea todo lo descargado e imprime stats agregadas
python scripts/parse_all.py

# Tests
pytest
```

La descarga cubre los últimos 20 Forms 4 de Apple, Microsoft, NVIDIA, Tesla y Meta (CIK fija) en `data/raw/form4/{cik}/{accession}/`. El bulk-parse procesa los 100 filings, valida la distribución de códigos contra el corpus, y no persiste nada — la persistencia llega en Fase 3.

## Roadmap

- [x] Fase 1 — Ingesta cruda de Forms 4
- [x] Fase 2 — Parseo de XML a estructuras tipadas + clasificación de códigos
- [ ] Fase 3 — Almacenamiento en SQLite con esquema normalizado
- [ ] Fase 4 — Análisis con pandas (agregaciones, métricas por insider/empresa)
- [ ] Fase 5 — Dashboard en Streamlit
- [ ] Soporte para Forms 3 y 5
- [ ] Modelado de holdings (`nonDerivativeHolding` / `derivativeHolding`)
- [ ] CI con GitHub Actions

## Stack

- Python 3.11+
- `requests` para HTTP
- `pandas` para análisis (fases posteriores)
- SQLite para almacenamiento (fases posteriores)
- Streamlit para la visualización (fases posteriores)
- pytest para tests (fases posteriores)

## Prior art (librerías existentes que no usamos)

Existen librerías como [`sec-edgar-downloader`](https://pypi.org/project/sec-edgar-downloader/) y [`edgar`](https://pypi.org/project/edgar/) que automatizan parte de esto. Este proyecto las evita a propósito: el objetivo es entender el protocolo de la SEC implementándolo desde cero.

## Reglas de la SEC respetadas

- `User-Agent` identificable en todas las requests (obligatorio).
- Rate limit conservador (~5 req/s, por debajo del límite oficial de 10 req/s).
- `Accept-Encoding: gzip, deflate`.

## Licencia

MIT — ver [LICENSE](LICENSE).
