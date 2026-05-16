# edgar-insider-tracker

Pipeline en Python para descargar, parsear y analizar **Forms 3/4/5** (insider trading) de [SEC EDGAR](https://www.sec.gov/edgar.shtml), con una capa de visualización en Streamlit.

No es un proyecto para "predecir el mercado". Es un proyecto de **ingesta y análisis riguroso de datos regulatorios reales**, honesto sobre los límites de lo que estas formas reportan.

## Estado actual: Fase 4 — Análisis honesto

El pipeline cubre descarga → parseo → almacenamiento → análisis con pandas + price impact contra precios diarios (yfinance, cacheados en la misma BBDD). Diseño explícitamente **sin scores compuestos**: cada función responde una pregunta concreta. Las estadísticas comparativas reportan `n` y marcan `warning` cuando la muestra es insuficiente — el proyecto trata la honestidad estadística como rasgo, no como caveat.

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

# Fase 4a: precios diarios desde Yahoo Finance (cachea en tabla `prices`)
python scripts/fetch_prices.py

# Fase 4b: informe completo de un ticker
python scripts/analyze.py --ticker TSLA
python scripts/analyze.py --ticker AAPL

# Tests
pytest
```

### Qué responde el análisis

Cada función vive en `src/edgar_insider/analysis/` y devuelve un `pd.DataFrame`:

- **`code_composition`** — % de cada código (P, S, F, M, A, G, D) por ticker
- **`signal_ratio`** — % de P sobre total + % de S bajo plan 10b5-1
- **`top_insiders_by_p`** — quién compra más, ordenado por nº y por notional
- **`monthly_activity`** — serie mensual de transacciones por código
- **`clustering_days`** — días en que ≥N insiders distintos compran en el mismo ticker
- **`net_flow_by_category`** — acquired vs disposed en shares y notional
- **`post_p_returns`** — return acumulado a +5/+10/+30 días tras cada P, vs baseline del mismo ticker. **Caveat explícito si n<30.**

### Hallazgos reales del corpus

Con N=393 transacciones en 5 megacaps:

- **TSLA**: 21% son P, pero las 25 P proceden de un único día (Musk, sep 2025). Tras ese único evento el +30d return fue +9.5% (vs baseline +5.4%). N=1 evento real — no es una conclusión, es una anécdota.
- **AAPL**: **0 compras P** en los últimos 20 filings. Los insiders monetizan equity comp (52% son M, 21% son S); ningún oficial pone dinero propio.
- **De todas las S del corpus**, una mayoría aplastante está bajo plan 10b5-1 (pre-agendadas) — menos señal informativa que una S no-planificada.

## Roadmap

- [x] Fase 1 — Ingesta cruda de Forms 4
- [x] Fase 2 — Parseo de XML a estructuras tipadas + clasificación de códigos
- [x] Fase 3 — Almacenamiento en SQLite con esquema normalizado e idempotente
- [x] Fase 4 — Análisis con pandas + price impact (yfinance) con honestidad estadística
- [ ] Fase 5 — Dashboard en Streamlit
- [ ] Soporte para Forms 3 y 5
- [ ] Modelado de holdings (`nonDerivativeHolding` / `derivativeHolding`)
- [ ] Flag `--rebuild` para reparsear filings ya cargados
- [ ] Benchmark vs SPY (alternativa a baseline intra-ticker)
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
