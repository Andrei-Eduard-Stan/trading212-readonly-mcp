from portfolio_accounting import aggregate_order_friction


def _order(*taxes):
    return {
        "id": 1,
        "fill": {
            "id": 10,
            "walletImpact": {
                "currency": "GBP",
                "taxes": list(taxes),
            },
        },
    }


def _tax(name, quantity, currency="GBP"):
    return {
        "name": name,
        "quantity": quantity,
        "currency": currency,
    }


def test_known_order_friction_is_classified():
    result = aggregate_order_friction(
        [
            _order(
                _tax("CURRENCY_CONVERSION_FEE", -1.50),
                _tax("FINRA_FEE", -0.20),
                _tax("STAMP_DUTY", -3.00),
            )
        ],
        "GBP",
    )

    assert result["complete"] is True
    assert result["fxFeesPaid"] == 1.50
    assert result["tradingFeesPaid"] == 0.20
    assert result["tradingTaxesAndLevies"] == 3.00
    assert result["unknownTypes"] == []


def test_unknown_order_tax_type_fails_closed():
    result = aggregate_order_friction(
        [_order(_tax("MYSTERY_LEVY", -2.00))],
        "GBP",
    )

    assert result["complete"] is False
    assert result["unknownTypes"] == ["MYSTERY_LEVY"]


def test_order_tax_currency_mismatch_fails_closed():
    result = aggregate_order_friction(
        [_order(_tax("STAMP_DUTY", -2.00, currency="EUR"))],
        "GBP",
    )

    assert result["complete"] is False
    assert result["currencyMismatches"] == ["EUR"]
