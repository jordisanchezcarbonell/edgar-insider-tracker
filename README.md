# edgar-insider-tracker

Pipeline en Python para descargar, parsear y analizar **Forms 3/4/5** (insider trading) de [SEC EDGAR](https://www.sec.gov/edgar.shtml), con una capa de visualización en Streamlit.

No es un proyecto para "predecir el mercado". Es un proyecto de **ingesta y análisis riguroso de datos regulatorios reales**, honesto sobre los límites de lo que estas formas reportan.

## Estado actual: Fase 1 — Ingesta

Fase 1 cubre solo la descarga de Forms 4 crudos desde la API pública de la SEC y su almacenamiento organizado en disco. No hay parsing, base de datos ni interfaz todavía.

### Cómo ejecutar la ingesta

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/download_initial_batch.py
```

Esto descarga los últimos 20 Forms 4 de cada una de estas 5 empresas (Apple, Microsoft, NVIDIA, Tesla, Meta) en `data/raw/form4/{cik}/{accession}/`. Re-ejecutar el script es idempotente: salta los filings ya descargados.

## Roadmap

- [x] Fase 1 — Ingesta cruda de Forms 4
- [ ] Fase 2 — Parseo de XML a estructuras tabulares
- [ ] Fase 3 — Almacenamiento en SQLite con esquema normalizado
- [ ] Fase 4 — Análisis con pandas (agregaciones, métricas por insider/empresa)
- [ ] Fase 5 — Dashboard en Streamlit
- [ ] Soporte para Forms 3 y 5
- [ ] Tests con pytest
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
