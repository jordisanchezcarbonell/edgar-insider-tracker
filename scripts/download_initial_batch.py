"""Entrypoint manual de Fase 1.

Descarga los últimos N Forms 4 de cada empresa en TARGET_CIKS y los guarda
en data/raw/form4/. Re-ejecutar es idempotente: salta los filings ya bajados.

Uso:
    python scripts/download_initial_batch.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Truco para que el script funcione sin instalar el paquete (`pip install -e .`):
# añadimos `src/` al sys.path. En un proyecto "real" haríamos el package
# install editable, pero en Fase 1 esto es lo más simple y didáctico.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from edgar_insider.config import MAX_FILINGS_PER_COMPANY, TARGET_CIKS  # noqa: E402
from edgar_insider.ingest.client import SecClient  # noqa: E402
from edgar_insider.ingest.downloader import download_company  # noqa: E402


def main() -> None:
    client = SecClient()
    for ticker, cik_padded in TARGET_CIKS.items():
        download_company(client, ticker, cik_padded, MAX_FILINGS_PER_COMPANY)
    print("\nFase 1 completa.")


if __name__ == "__main__":
    main()
