"""CLI de análisis de actividad insider para un ticker.

Reporta los bloques A (sin datos externos) y B (price impact, requiere
prices cargados con `scripts/fetch_prices.py`).

Uso:
    python scripts/analyze.py --ticker TSLA
    python scripts/analyze.py --ticker AAPL --windows 5 20 60
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import pandas as pd  # noqa: E402

from edgar_insider.analysis.metrics import (  # noqa: E402
    clustering_days,
    code_composition,
    monthly_activity,
    net_flow_by_category,
    signal_ratio,
    top_insiders_by_p,
)
from edgar_insider.analysis.price_impact import post_p_returns  # noqa: E402
from edgar_insider.analysis.queries import list_tickers, load_transactions  # noqa: E402
from edgar_insider.config import DB_PATH  # noqa: E402
from edgar_insider.storage.schema import connect  # noqa: E402


def _section(title: str) -> None:
    print(f"\n--- {title} ---")


def _print_df(df: pd.DataFrame, *, max_rows: int = 25) -> None:
    if df.empty:
        print("  (sin datos)")
        return
    # Estiliza para imprimir sin truncamientos raros.
    with pd.option_context("display.max_rows", max_rows,
                           "display.max_columns", None,
                           "display.width", 200,
                           "display.float_format", "{:.4f}".format):
        print(df.to_string(index=False))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True, help="Ticker a analizar (ej. TSLA)")
    parser.add_argument("--windows", nargs="+", type=int, default=[5, 10, 30],
                        help="Días de horizonte para price impact (default: 5 10 30)")
    parser.add_argument("--top", type=int, default=5,
                        help="Top N insiders por compras P (default: 5)")
    args = parser.parse_args()

    conn = connect(DB_PATH)

    available = list_tickers(conn)
    if args.ticker not in available:
        print(f"Ticker {args.ticker!r} no está en la BBDD.")
        print(f"Disponibles: {', '.join(available) or '(ninguno — carga datos primero)'}")
        return 2

    tx = load_transactions(conn, ticker=args.ticker)
    issuer_name = tx["issuer_name"].iloc[0] if not tx.empty else ""
    n_tx = len(tx)
    n_insiders = tx["insider_cik"].nunique() if not tx.empty else 0
    n_filings = tx["accession_number"].nunique() if not tx.empty else 0

    print(f"\n=== {args.ticker} — {issuer_name} ===")
    print(f"  Transacciones: {n_tx}  |  Insiders únicos: {n_insiders}  |  Filings: {n_filings}")

    _section("Composición de códigos")
    _print_df(code_composition(tx))

    _section("Señal vs ruido")
    sig = signal_ratio(tx)
    _print_df(sig)
    if not sig.empty:
        row = sig.iloc[0]
        print(
            f"\n  Interpretación: el {row['p_share']:.1%} de las transacciones son P "
            f"(compras reales de mercado). De las {row['n_s_total']} ventas, "
            f"{row['planned_s_share']:.1%} están bajo plan 10b5-1 (pre-agendadas — "
            f"menos señal informativa)."
        )

    _section(f"Top {args.top} insiders por compras P")
    _print_df(top_insiders_by_p(tx, top_n=args.top))

    _section("Actividad mensual (cuenta por código)")
    _print_df(monthly_activity(tx), max_rows=60)

    _section("Días con clustering (≥2 insiders distintos comprando)")
    _print_df(clustering_days(tx, min_distinct_insiders=2))

    _section("Net flow por categoría (acquired - disposed)")
    _print_df(net_flow_by_category(tx))

    _section(f"Price impact post-P (horizontes {args.windows} días)")
    pir = post_p_returns(conn, args.ticker, windows=tuple(args.windows))
    if pir.empty:
        print("  (no hay precios cargados; ejecuta `python scripts/fetch_prices.py`)")
    else:
        _print_df(pir)
        # Caveat obligatorio si alguna ventana tiene warning
        warnings = pir["warning"].dropna()
        if not warnings.empty:
            print(
                f"\n  *** CAVEAT: la muestra de P-transactions en {args.ticker} es pequeña. "
                f"Estos números son DESCRIPTIVOS, no predictivos. "
                f"No se pueden derivar p-values ni intervalos de confianza con este N. ***"
            )

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
