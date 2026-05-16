"""Códigos de transacción de Form 4 y su categorización analítica.

La SEC define un alfabeto de códigos (P, S, A, F, M, …) en el reverso del
formulario oficial. Aquí los agrupamos en categorías más útiles para análisis
("¿es una compra real?", "¿es venta discrecional o retención fiscal?", etc.).

La distinción más importante para Fase 4 es S vs F: ambos reducen la posición
pero F es una retención de acciones por la empresa para pagar impuestos sobre
vesting — no es una decisión de vender. Tratar F como sale es el error #1 de
cualquier "insider sentiment" hecho mal.

Diseño: dict[str, CodeInfo] en lugar de Enum. El código es un string que llega
del XML y queremos un lookup O(1) directo, sin tener que convertir. Además, si
la SEC añade un código nuevo, basta con sumarlo al dict; un Enum requeriría
modificar más cosas.
"""

from __future__ import annotations

from dataclasses import dataclass

UNKNOWN_CATEGORY = "unknown"


@dataclass(frozen=True)
class CodeInfo:
    code: str
    official_name: str
    category: str


TRANSACTION_CODES: dict[str, CodeInfo] = {
    # --- Compraventas reales en mercado ---
    "P": CodeInfo("P", "Open market or private purchase", "open_market_purchase"),
    "S": CodeInfo("S", "Open market or private sale", "open_market_sale"),
    # --- Grants / awards y disposiciones internas ---
    "A": CodeInfo("A", "Grant or award (Rule 16b-3(d))", "award_grant"),
    "D": CodeInfo("D", "Disposition to issuer (Rule 16b-3(e))", "disposition_to_issuer"),
    # --- Retención fiscal: ojo, NO es venta discrecional ---
    "F": CodeInfo("F", "Payment of exercise price or tax liability by delivering/withholding securities", "tax_withholding"),
    "I": CodeInfo("I", "Discretionary transaction (Rule 16b-3(f))", "discretionary_plan"),
    # --- Derivados ---
    "M": CodeInfo("M", "Exercise/conversion of derivative (Rule 16b-3 exempt)", "derivative_exercise"),
    "C": CodeInfo("C", "Conversion of derivative security", "conversion"),
    "E": CodeInfo("E", "Expiration of short derivative position", "derivative_expiration"),
    "H": CodeInfo("H", "Expiration/cancellation of long derivative with value received", "derivative_expiration"),
    "O": CodeInfo("O", "Exercise of out-of-the-money derivative security", "derivative_exercise"),
    "X": CodeInfo("X", "Exercise of in/at-the-money derivative security", "derivative_exercise"),
    # --- Otros ---
    "G": CodeInfo("G", "Bona fide gift", "gift"),
    "L": CodeInfo("L", "Small acquisition (Rule 16a-6)", "small_acquisition"),
    "W": CodeInfo("W", "Acquisition/disposition by will or descent", "inheritance"),
    "Z": CodeInfo("Z", "Voting trust deposit or withdrawal", "voting_trust"),
    "J": CodeInfo("J", "Other acquisition/disposition (footnote required)", "other"),
    "K": CodeInfo("K", "Equity swap or instrument with similar characteristics", "equity_swap"),
    "U": CodeInfo("U", "Disposition pursuant to tender in change-of-control", "tender_offer"),
}


def categorize(code: str) -> str:
    """Devuelve la categoría analítica de un código de transacción.

    Si el código no existe en la tabla (la SEC podría introducir uno nuevo)
    devolvemos 'unknown' en vez de levantar excepción: queremos que el
    análisis siga funcionando con un bucket residual visible.
    """
    info = TRANSACTION_CODES.get(code)
    return info.category if info else UNKNOWN_CATEGORY
