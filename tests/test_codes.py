"""Tests de categorización de códigos.

Foco especial en la distinción S vs F: las dos reducen posición pero F NO es
una venta discrecional (es retención fiscal sobre vesting). Confundirlas
corrompería cualquier análisis de "insider sentiment", así que tenemos un
test explícito por si alguien tocara la tabla en el futuro.
"""

from edgar_insider.parse.codes import TRANSACTION_CODES, UNKNOWN_CATEGORY, categorize


def test_open_market_purchase_categorized_correctly():
    assert categorize("P") == "open_market_purchase"


def test_open_market_sale_categorized_correctly():
    assert categorize("S") == "open_market_sale"


def test_tax_withholding_is_not_a_sale():
    # La regresión que más miedo da: que alguien fusione F con S.
    assert categorize("F") == "tax_withholding"
    assert categorize("F") != categorize("S")


def test_grants_are_not_purchases():
    # A (award) suma posición pero no es señal alcista.
    assert categorize("A") == "award_grant"
    assert categorize("A") != categorize("P")


def test_derivative_exercise_codes_share_category():
    # M, O, X comparten categoría — todos son "ejercer un derivado".
    assert categorize("M") == "derivative_exercise"
    assert categorize("O") == "derivative_exercise"
    assert categorize("X") == "derivative_exercise"


def test_gift_categorized():
    assert categorize("G") == "gift"


def test_unknown_code_falls_back_gracefully():
    # Que la SEC introduzca un código nuevo no debe crashear el pipeline.
    assert categorize("ZZZ") == UNKNOWN_CATEGORY
    assert categorize("") == UNKNOWN_CATEGORY


def test_all_codes_have_non_empty_category():
    for code, info in TRANSACTION_CODES.items():
        assert info.code == code
        assert info.category, f"código {code} sin categoría"
        assert info.official_name, f"código {code} sin nombre oficial"
