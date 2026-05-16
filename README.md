# edgar-insider-tracker

Pipeline en Python para descargar, parsear y analizar **Forms 3/4/5** (insider trading) de [SEC EDGAR](https://www.sec.gov/edgar.shtml), con una capa de visualización en Streamlit.

No es un proyecto para "predecir el mercado". Es un proyecto de **ingesta y análisis riguroso de datos regulatorios reales**, honesto sobre los límites de lo que estas formas reportan.

## Estado actual: Fase 3 — Almacenamiento en SQLite

El pipeline cubre ya descarga → parseo → almacenamiento. Los Forms 4 crudos se persisten en una BBDD SQLite normalizada (`issuers`, `insiders`, `filings`, `insider_transactions`) en `data/edgar.db`, con re-ejecuciones idempotentes garantizadas a nivel de esquema (UNIQUE + INSERT OR IGNORE) y FK activas vía `PRAGMA foreign_keys = ON`.

### Cómo ejecutar

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Fase 1: descarga (idempotente)
python scripts/download_initial_batch.py

# Fase 2: parsea e imprime stats (no persiste)
python scripts/parse_all.py

# Fase 3: parsea y carga a SQLite (idempotente)
python scripts/load_all.py

# Tests
pytest
```

La descarga cubre los últimos 20 Forms 4 de Apple, Microsoft, NVIDIA, Tesla y Meta. Tras `load_all.py`, la BBDD contiene 5 issuers, 55 insiders, 100 filings y 393 transacciones. Inspeccionable con el CLI estándar de SQLite:

```bash
sqlite3 data/edgar.db
sqlite> SELECT transaction_code, COUNT(*) FROM insider_transactions GROUP BY 1 ORDER BY 2 DESC;
```

## Roadmap

- [x] Fase 1 — Ingesta cruda de Forms 4
- [x] Fase 2 — Parseo de XML a estructuras tipadas + clasificación de códigos
- [x] Fase 3 — Almacenamiento en SQLite con esquema normalizado e idempotente
- [ ] Fase 4 — Análisis con pandas (agregaciones, métricas por insider/empresa)
- [ ] Fase 5 — Dashboard en Streamlit
- [ ] Soporte para Forms 3 y 5
- [ ] Modelado de holdings (`nonDerivativeHolding` / `derivativeHolding`)
- [ ] Flag `--rebuild` para reparsear filings ya cargados
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
