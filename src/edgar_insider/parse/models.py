"""Dataclasses inmutables que representan un Form 4 parseado.

Diseño:
- Todas frozen → mutación accidental rompe ruidosamente; hashables; comparables.
- Tuplas en lugar de listas para colecciones → coherente con inmutabilidad.
- `Decimal` para todo lo numérico financiero. Usar float aquí sería un bug
  esperando a pasar (errores de redondeo silenciosos en agregaciones).
- Campos opcionales con `| None`: el XML de la SEC varía entre versiones de
  schema y entre filers; modelamos la realidad, no el ideal.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Mapping


class Form4ParseError(Exception):
    """Fallo al parsear un Form 4 concreto.

    Lleva el accession opcional para que el caller (bulk-parse script) pueda
    loguear "qué filing falló" y continuar con el siguiente, en vez de abortar
    todo el batch ante un único XML raro.
    """

    def __init__(self, message: str, *, accession: str | None = None) -> None:
        super().__init__(message)
        self.accession = accession


@dataclass(frozen=True)
class Issuer:
    cik: str
    name: str
    ticker: str


@dataclass(frozen=True)
class Insider:
    cik: str
    name: str
    is_director: bool
    is_officer: bool
    is_ten_percent_owner: bool
    is_other: bool
    officer_title: str | None
    other_text: str | None


@dataclass(frozen=True)
class Transaction:
    # Comunes a non-derivative y derivative
    security_title: str
    transaction_date: date
    transaction_code: str          # 'P', 'S', 'F', 'M', …
    transaction_category: str      # derivado: 'open_market_purchase', 'tax_withholding', …
    is_derivative: bool
    shares: Decimal
    price_per_share: Decimal | None
    acquired_or_disposed: str      # 'A' (adquirido) o 'D' (dispuesto) — campo SEC
    shares_owned_following: Decimal | None
    ownership_nature: str          # 'D' directa o 'I' indirecta
    indirect_owner_explanation: str | None
    footnote_ids: tuple[str, ...]
    # Solo derivativeTransaction (None en non-derivative)
    conversion_or_exercise_price: Decimal | None
    expiration_date: date | None
    underlying_security_title: str | None
    underlying_shares: Decimal | None


@dataclass(frozen=True)
class ParsedFiling:
    schema_version: str
    document_type: str
    period_of_report: date
    is_amendment: bool
    not_subject_to_section_16: bool
    under_10b5_1_plan: bool
    issuer: Issuer
    reporting_owners: tuple[Insider, ...]
    transactions: tuple[Transaction, ...]
    footnotes: Mapping[str, str]
    # Conteo de `nonDerivativeHolding` + `derivativeHolding` saltadas.
    # No las modelamos en Fase 2 (no son transacciones), pero las contamos
    # para visibilidad y para reabrir la decisión en Fase 4 si hace falta.
    skipped_holdings_count: int
