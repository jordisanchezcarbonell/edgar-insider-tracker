"""Descarga OHLCV diario para los TARGET_CIKS desde Yahoo Finance.

Cachea en la tabla `prices` de SQLite. Idempotente vía `INSERT OR REPLACE`
(un re-fetch actualiza valores ajustados ante splits/dividendos posteriores).

Uso:
    python scripts/fetch_prices.py
    python scripts/fetch_prices.py --start 2024-01-01 --end 2026-12-31
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from edgar_insider.analysis.price_impact import ensure_prices  # noqa: E402
from edgar_insider.config import DB_PATH, TARGET_CIKS  # noqa: E402
from edgar_insider.storage.schema import connect, create_tables  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--start",
        default="2024-01-01",
        help="Fecha inicio (YYYY-MM-DD). Default: 2024-01-01 (≈2 años de baseline)",
    )
    parser.add_argument(
        "--end",
        default="2026-12-31",
        help="Fecha fin (YYYY-MM-DD)",
    )
    args = parser.parse_args()

    conn = connect(DB_PATH)
    create_tables(conn)

    tickers = list(TARGET_CIKS.keys())
    print(f"Descargando OHLCV para {tickers} desde {args.start} hasta {args.end}…")
    result = ensure_prices(conn, tickers, start=args.start, end=args.end)

    print("\n=== Resumen ===")
    for ticker, n in result.items():
        print(f"  {ticker:6s} {n:5d} filas insertadas/actualizadas")

    total_rows = conn.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
    print(f"\nTotal en tabla prices: {total_rows} filas")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
