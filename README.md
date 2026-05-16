# edgar-insider-tracker

[![tests](https://github.com/jordisanchezcarbonell/edgar-insider-tracker/actions/workflows/test.yml/badge.svg)](https://github.com/jordisanchezcarbonell/edgar-insider-tracker/actions/workflows/test.yml)
[![python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/downloads/)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

An end-to-end pipeline that ingests **Form 4 insider transactions** from SEC EDGAR, parses the XML to typed dataclasses, persists to a normalized SQLite database, runs honest analysis (no magic scores), and serves it via a Streamlit dashboard.

The project's defining constraint: **be statistically honest**. Sample sizes are small (≈400 transactions across 5 large-caps), so the dashboard reports `n` everywhere and flags any comparative statistic where `n < 30`. This is a tool for understanding insider activity transparently — not a "smart money signal".

## Live demo

🟢 **App**: [edgar-insider-tracker.streamlit.app](https://share.streamlit.io/) *(deploy from this repo via [share.streamlit.io](https://share.streamlit.io); the snapshot DB at `data/edgar.db` is committed so the cloud build needs no pipeline run)*

## Screenshots

> _To populate these: run `streamlit run app.py`, pick **TSLA**, take the screenshots and drop them into `docs/screenshots/`. See [bottom of README](#screenshots-howto)._

| Dashboard overview (TSLA) | Price + insider P markers |
|---|---|
| ![Overview](docs/screenshots/overview.png) | ![Price chart](docs/screenshots/price_with_p.png) |

## What it does

1. **Downloads** the latest Form 4 filings for a fixed set of issuers (AAPL, MSFT, NVDA, TSLA, META) from SEC EDGAR's free public API, respecting the SEC's `User-Agent` and rate-limit rules.
2. **Parses** the XML schema (handles both `X0508` and `X0609` variants, the `<value>` wrapper convention, scattered `footnoteId` references, indirect ownership vehicles).
3. **Categorizes** each transaction code into analytical buckets — critically separating `F` (tax withholding) from `S` (real sale) and `P` (open-market purchase) from `A` (award grant). Confusing these is the #1 mistake in retail "insider signal" tools.
4. **Stores** in a normalized SQLite database (4 tables, idempotent loads, FK enforcement).
5. **Analyzes** with pandas: code composition, signal ratios, top buyers, monthly activity, clustering, net flow, and post-P price impact (against daily Yahoo Finance prices, also cached locally).
6. **Visualizes** in a Streamlit dashboard where real buys (`P`) jump out visually and statistical caveats are non-optional.

## Key findings on the current corpus

These come straight out of running `python scripts/analyze.py --ticker XXX` on the 393-transaction corpus. They illustrate why honest reporting matters more than averaging things together:

- **TSLA**: 21% of recent transactions are `P`, but **all 25 P happened on a single day** (Musk, September 2025). Post-event +30-day return is +9.5% vs intra-ticker baseline +5.4%. Effective N is **1 event**, not 25 — the dashboard surfaces this caveat prominently.
- **AAPL**: zero `P` transactions across the last 20 filings. Apple insiders monetize equity compensation (52% are `M` derivative exercises, 21% are `S` sales) but no officer puts personal cash in.
- **In TSLA and AAPL, over 80% of sales are under Rule 10b5-1 plans** (pre-scheduled months in advance), which strips most of their informational content.

The takeaway is structural: a naive "insider buying ratio" would mislead in opposite directions for these two tickers. Per-code, per-context analysis is the only honest read.

## Data scope — what's in the corpus, what isn't

A reasonable first question from anyone evaluating this project is "do you understand the boundaries of your data?". The honest answer:

**What we have**

- **5 issuers, fixed**: AAPL, MSFT, NVDA, TSLA, META (chosen as large-caps with consistent reporting infrastructure; see `TARGET_CIKS` in `src/edgar_insider/config.py`).
- **20 most-recent Form 4 filings per issuer = 100 filings = 393 transactions** at the time of the committed snapshot. The number depends on when the pipeline was last run.
- **Date range**: roughly August 2025 → May 2026 (≈9 months). Concentrated more in recent months because Form 4 filings cluster around earnings windows.
- **Daily OHLCV from Yahoo Finance** for the same 5 tickers, January 2024 → present (~2.4 years), cached in the same SQLite DB.

**What we do NOT have, even though it would be reachable from the same SEC API**

- Older filings — the `submissions/CIK*.json` endpoint returns the most recent ~1000 per CIK, and `filings.files[]` exposes the historical chunks; we only consume `filings.recent` and cap at 20. Going back further is a config change (`MAX_FILINGS_PER_COMPANY`) plus a re-run, not a code change.
- Other tickers — adding more issuers is a config dict edit and a re-run.
- Forms 3 (initial ownership), Forms 5 (annual late-filing summary), Forms 13F (institutional holdings), Schedule 13D/G (5%+ ownership) — out of scope.
- `nonDerivativeHolding` / `derivativeHolding` entries within Form 4s — these are position-only reports without a transaction, and we deliberately skip them (count is logged in `parse_all.py`).

**Why a small sample on purpose**

The project's value is the *pipeline and the analytical honesty*, not the size of the dataset. A 393-transaction corpus is large enough to exercise every parser branch, code category, and edge case (multi-owner filings, indirect ownership vehicles, 10b5-1 plans, fractional shares from RSU vesting), and small enough that re-running the full pipeline takes under a minute. Scaling to thousands of filings is a configuration change, not new code — see the roadmap.

**How to verify the corpus is what we claim**

```bash
sqlite3 data/edgar.db "SELECT i.ticker, COUNT(DISTINCT f.accession_number) AS filings,
                              COUNT(t.id) AS transactions,
                              MIN(t.transaction_date) AS earliest,
                              MAX(t.transaction_date) AS latest
                       FROM issuers i
                       JOIN filings f ON f.issuer_cik = i.cik
                       JOIN insider_transactions t ON t.accession_number = f.accession_number
                       GROUP BY i.ticker"
```

## Architecture

```
            SEC EDGAR API                    Yahoo Finance
                 │                                │
                 ▼                                ▼
  ┌──────────────────────────┐    ┌──────────────────────────┐
  │ Phase 1: ingest          │    │ Phase 4a: fetch_prices   │
  │ download_initial_batch   │    │ ensure_prices (yfinance) │
  │ raw XML on disk          │    │                          │
  └────────────┬─────────────┘    └────────────┬─────────────┘
               │                                │
               ▼                                │
  ┌──────────────────────────┐                  │
  │ Phase 2: parse           │                  │
  │ XML -> typed dataclasses │                  │
  │ (codes categorized)      │                  │
  └────────────┬─────────────┘                  │
               │                                │
               ▼                                ▼
  ┌──────────────────────────────────────────────────┐
  │ Phase 3 + 4 storage: SQLite (data/edgar.db)      │
  │ issuers · insiders · filings · insider_tx · prices│
  │ idempotent, FK enforced, INSERT OR IGNORE        │
  └────────────┬─────────────────────────────────────┘
               │
               ▼
  ┌──────────────────────────┐         ┌──────────────────────────┐
  │ Phase 4 analysis (pandas)│ ──────▶ │ Phase 5: Streamlit app   │
  │ metrics + price_impact   │         │ filters · charts · tables│
  └──────────────────────────┘         └──────────────────────────┘
```

The pipeline is split into independent phases: each can be re-run safely (everything is idempotent), inspected via its CLI, and tested in isolation.

## Tech stack and rationale

| Component | Choice | Why this and not something else |
|---|---|---|
| HTTP client | `requests` | Sync is fine for ~100 filings; one less concept than `httpx`. |
| XML parser | `xml.etree.ElementTree` (stdlib) | SEC is a trusted source; no XXE/billion-laughs risk. Zero new dependency. |
| Database | SQLite (`sqlite3` stdlib) | Single-file, portable, deployable to Streamlit Community Cloud with the snapshot committed. No server to run. No ORM hides the SQL. |
| DataFrames | pandas | Idiomatic for tabular analysis; `read_sql_query` and `groupby` cover 90% of what we do. |
| Price data | `yfinance` | Free, no API key. Risk (unofficial scraping) mitigated by caching prices in our own DB. |
| Visualization | Plotly via `st.plotly_chart` | Best Streamlit integration; rich hover tooltips out of box; color maps respect our palette. |
| UI | Streamlit | Pure Python, fast to iterate, deploys free to Community Cloud. |
| Tests | pytest | Standard. Fixtures = real XMLs from `data/raw/` for parser tests; synthetic SQLite for storage/analysis tests. |

## Quickstart

```bash
git clone https://github.com/jordisanchezcarbonell/edgar-insider-tracker.git
cd edgar-insider-tracker

python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Option A — use the committed snapshot
streamlit run app.py        # opens http://localhost:8501
# The dashboard defaults to the ticker with the most P transactions
# (TSLA in the current corpus) so the first thing the visitor sees is
# the most signal-rich case, not an empty AAPL screen.

# Option B — rebuild the dataset from scratch (idempotent)
python scripts/download_initial_batch.py    # SEC Forms 4
python scripts/load_all.py                  # parse + load SQLite
python scripts/fetch_prices.py              # Yahoo OHLCV
streamlit run app.py
```

Run the analysis as a CLI (no UI):

```bash
python scripts/analyze.py --ticker TSLA
python scripts/analyze.py --ticker AAPL --windows 5 20 60
```

## Known limitations

This section is intentionally long. The most common mistake in projects like this is to oversell what insider data can tell you.

- **Forms 4 are not real-time.** They must be filed within 2 business days of a transaction. The dashboard never reflects intraday activity. It is not suitable for tactical trading decisions.
- **The corpus is tiny by statistical standards.** 393 transactions across 5 issuers and ~9 months. Any aggregate "average return after a P transaction" is descriptive, not inferential. The dashboard refuses to compute p-values or confidence intervals at this scale. See the [Data scope section](#data-scope--whats-in-the-corpus-what-isnt) above for the exact boundaries and how to expand.
- **One event dominates the entire P signal.** 25 of the 26 P transactions in the corpus come from a single Musk filing day in September 2025. Any statement like "P transactions average +9% in 30 days" is effectively a measurement of one event.
- **We only ingest Form 4.** Forms 3 (initial ownership) and 5 (annual late-filing summary) are out of scope, as are Forms 13F (institutional holdings) and 13D/G (5%+ ownership). Coverage is partial.
- **We skip `nonDerivativeHolding` and `derivativeHolding` entries.** These report static positions (e.g. shares held in a trust) without an underlying transaction. The skip count is reported in `scripts/parse_all.py` so the magnitude is visible.
- **The price baseline is intra-ticker, not market-relative.** We compare post-P returns to the return of all N-day windows in the same ticker's history. This controls for the ticker's regime but not for SPY or sector. A real factor-model attribution is out of scope.
- **Yahoo Finance is an unofficial source.** `yfinance` scrapes Yahoo; the contract can change without notice. Cached prices in `data/edgar.db` mean an analysis run still works offline, but a fresh fetch can fail.
- **Officer titles, names, and roles can vary across filings.** The `insiders` table stores the first-seen name per CIK. A name change between filings is silently ignored.
- **Form 4 reports everything subject to Section 16, not just "interesting" trades.** Vesting (`A`), tax withholding (`F`), and derivative exercises (`M`) are all reported and dominate the volume. Treating raw transaction counts as a "trading signal" is the classical retail mistake this project is built to avoid.
- **Academic context.** The insider-trading literature (Lakonishok & Lee 2001, Cohen et al. 2012) finds that insider purchases — specifically real `P` transactions by senior officers — outperform a market benchmark by a small, slowly-decaying margin. This is real but small, and competes with transaction costs. Nothing here should be read as an edge.
- **Snapshot DB at `data/edgar.db` is refreshed manually.** A `git push` after re-running the local pipeline is the only way the cloud-deployed app sees new data.

## Design decisions worth defending

A few choices that are not obvious from reading the code:

- **No composite scores or hand-tuned weights.** Every metric answers a single, specific question. Combination is left to the reader.
- **SQLite over Postgres.** A 1MB single file beats a server when the dataset is tiny and the goal is portability. The committed snapshot _is_ the deploy artifact.
- **`INSERT OR IGNORE` on UNIQUE constraints**, not application-level "SELECT first then INSERT". The database is the authority on uniqueness, which avoids race conditions and is faster.
- **`PRAGMA foreign_keys = ON` per connection.** SQLite has FK enforcement off by default — this is the classical foot-gun. The `connect()` wrapper sets it; a regression test verifies it.
- **`@dataclass(frozen=True)` + tuples everywhere.** If the container is immutable, its collections should be too. Mutating accidentally raises loudly.
- **`Decimal` in the parser, `REAL` in the database.** Parsing financial strings demands `Decimal`. SQLite `NUMERIC` is unreliable for precision, so we drop to `REAL` at the storage boundary and accept the float trade-off (documented; acceptable for prices). For exact arithmetic, round-trip through `Decimal` in Python.
- **Charts module separate from `app.py`.** Plot functions return `go.Figure` so they're importable from notebooks or testable without Streamlit.
- **Statistical caveats are programmatic, not optional.** Any output where `n < 30` carries an explicit `warning` field. The Streamlit banner is a prominent yellow box. This separates the project from "insider sentiment" tools that promise alpha with `n = 12`.
- **Display formatting in `ui/labels.py`, not in storage.** The DB keeps raw SEC values (`MICROSOFT CORP`, `MURDOCH JAMES R`, `open_market_purchase`) as the source of truth. Title-casing, per-ticker display names, and a derived `Rol` column (which combines `officer_title` with the `is_director` / `is_ten_percent_owner` flags so pure directors don't show as blank) live at the presentation boundary.
- **Default ticker is data-driven.** The dashboard opens on the ticker with the most `P` transactions in the corpus, not the alphabetical first. Otherwise a visitor's first impression of AAPL would be three empty-state messages in a row, which misrepresents what the app does.

## Testing

```bash
pytest -v           # 57 tests across parsing, storage, analysis, and display labels
```

Test fixtures are split deliberately:
- **Parser tests** use real XMLs copied from `data/raw/form4/` (in `tests/fixtures/`) — SEC documentation is ambiguous in places; the actual filings are the ground truth.
- **Storage tests** use a temporary SQLite in `tmp_path` so each test starts clean and FK enforcement is genuinely tested.
- **Analysis tests** build synthetic transactions and synthetic prices directly via SQL — they run offline, never touching yfinance or the SEC.

CI runs on every push and PR to `main` against Python 3.11 and 3.12 ([workflow](.github/workflows/test.yml)).

## Roadmap

Items deliberately deferred:

- Support for Forms 3 and 5 (similar schema to Form 4, manageable extension)
- Model `nonDerivativeHolding` / `derivativeHolding` as a separate `holdings` entity
- `--rebuild` flag on the loader for reparsing already-loaded filings
- Baseline against SPY / sector instead of (or alongside) intra-ticker windows
- Forms 13F for institutional context (different schema, different cadence)
- More issuers in `TARGET_CIKS` — currently fixed at 5; making this configurable is trivial but increases pipeline runtime

## Data sources and license

- **SEC EDGAR** — public, free, no API key. Used in accordance with [SEC's access policy](https://www.sec.gov/os/accessing-edgar-data) (identifying `User-Agent`, ≤10 req/s; we run at ≈5 req/s).
- **Yahoo Finance** — via `yfinance`, unofficial scraping. Cached locally to minimize requests.
- **Code**: MIT — see [LICENSE](LICENSE).

## <a name="screenshots-howto"></a>Appendix — taking screenshots for the README

I can't take screenshots from here. To populate the table at the top:

```bash
streamlit run app.py
# The dashboard opens directly on TSLA (the data-driven default) —
# no need to switch tickers before screenshotting the demo case.
#
# 1. Screenshot the full page including KPIs + monthly chart
#       -> docs/screenshots/overview.png
# 2. Screenshot just the "Precio del ticker con compras P marcadas" chart
#       -> docs/screenshots/price_with_p.png

mkdir -p docs/screenshots
# drop the .png files there, then git add + commit
```

---

## TL;DR en español

**Qué es**: pipeline en Python + dashboard Streamlit que descarga Forms 4 (transacciones de insiders) de SEC EDGAR, los parsea, los guarda en SQLite normalizada, los analiza con pandas y los visualiza distinguiendo señal (`P` = compra real de mercado) de ruido (`S` bajo plan 10b5-1, `F` retención fiscal, `M` ejercicio de opciones, etc.).

**Por qué importa la honestidad estadística**: el corpus actual son ~400 transacciones de 5 empresas en 9 meses (muestra deliberadamente pequeña — ver sección "Data scope"). Cualquier "score insider sentiment" calculado con N tan pequeño es matemática-decorativa. Este proyecto reporta siempre `n` y marca con un banner amarillo cualquier comparativa con `n < 30`. No promete alfa que no tiene.

**Hallazgos reales del corpus**:
- TSLA: 25 de las 26 compras `P` del corpus son de un solo día de Musk (sept 2025). N efectivo = 1 evento.
- AAPL: 0 compras `P` en los últimos 20 filings — los insiders solo monetizan equity comp.
- En TSLA y AAPL, >80% de las ventas están bajo plan 10b5-1 (pre-agendadas), lo que reduce su valor informativo.

**Cómo correrlo**:
```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py    # usa el snapshot commiteado en data/edgar.db
```

**Limitaciones principales** (la sección completa, en inglés, arriba): los Forms 4 se publican con hasta 2 días de retraso, la muestra es minúscula, solo cubrimos 5 empresas y Forms 4, yfinance es scraping no oficial, no modelamos holdings, la baseline es intra-ticker (no SPY). El proyecto está construido **alrededor** de estas limitaciones, no a pesar de ellas — saber qué NO te dicen los datos es tan importante como saber qué te dicen.

**Stack**: Python 3.11+, requests, pandas, SQLite stdlib, yfinance, Streamlit, Plotly, pytest. Cero ORMs, cero deps innecesarias.
