from portfolio_accounting import classify_transactions


def _tx(tx_type, amount, *, currency="GBP", date="2025-01-01T00:00:00Z", reference=None):
    return {
        "type": tx_type,
        "amount": amount,
        "currency": currency,
        "dateTime": date,
        "reference": reference or f"{tx_type}-{amount}",
    }


def test_known_account_boundary_flows_are_classified_correctly():
    result = classify_transactions(
        [
            _tx("DEPOSIT", 1000, reference="deposit"),
            _tx("WITHDRAW", 200, reference="withdraw"),
            _tx("TRANSFER", 300, reference="transfer-in"),
            _tx("TRANSFER", -50, reference="transfer-out"),
            _tx("INTEREST_ON_FREE_CASH", 10, reference="interest"),
            _tx("FEE", -5, reference="fee"),
        ],
        "GBP",
    )

    assert result["complete"] is True
    assert result["netAccountContributions"] == 1050
    assert result["interestReceived"] == 10
    assert result["genericAccountFees"] == 5
    assert len(result["accountBoundaryCashFlows"]) == 4
    assert result["unknownTypes"] == []
    assert result["currencyMismatches"] == []
    assert result["malformedCount"] == 0


def test_interest_is_not_external_contributed_capital():
    result = classify_transactions(
        [
            _tx("DEPOSIT", 1000, reference="deposit"),
            _tx("INTEREST_ON_FREE_CASH", 25, reference="interest"),
        ],
        "GBP",
    )

    assert result["complete"] is True
    assert result["netAccountContributions"] == 1000
    assert result["interestReceived"] == 25
    assert len(result["accountBoundaryCashFlows"]) == 1


def test_unknown_transaction_type_fails_closed():
    result = classify_transactions(
        [_tx("UNRECOGNISED_EVENT", 100)],
        "GBP",
    )

    assert result["complete"] is False
    assert result["netAccountContributions"] is None
    assert result["unknownTypes"] == ["UNRECOGNISED_EVENT"]


def test_currency_mismatch_fails_closed():
    result = classify_transactions(
        [_tx("DEPOSIT", 100, currency="EUR")],
        "GBP",
    )

    assert result["complete"] is False
    assert result["netAccountContributions"] is None
    assert result["currencyMismatches"] == ["EUR"]
