import pytest

from portfolio_accounting import AccountingError, build_portfolio_snapshot


AS_OF = "2026-01-01T00:00:00+00:00"


def _summary():
    return {
        "currency": "GBP",
        "totalValue": 1300.0,
        "investments": {
            "currentValue": 900.0,
            "totalCost": 800.0,
            "realizedProfitLoss": 50.0,
            "unrealizedProfitLoss": 100.0,
        },
        "cash": {
            "availableToTrade": 350.0,
            "reservedForOrders": 50.0,
            "inPies": 100.0,
        },
    }


def _deposit(amount=1000.0):
    return {
        "type": "DEPOSIT",
        "amount": amount,
        "currency": "GBP",
        "dateTime": "2025-01-01T00:00:00+00:00",
        "reference": "deposit-1",
    }


def _build(*, transactions=None, transactions_complete=True, account_summary=None):
    if transactions is None:
        transactions = [_deposit()]

    return build_portfolio_snapshot(
        account_summary=account_summary or _summary(),
        positions=[{"ticker": "TEST"}],
        transactions=transactions,
        transactions_complete=transactions_complete,
        dividends=[],
        dividends_complete=True,
        historical_orders=[],
        historical_orders_complete=True,
        pending_orders=[],
        as_of=AS_OF,
    )


def test_canonical_snapshot_accounting_semantics():
    snapshot = _build()

    assert snapshot["schemaVersion"] == "portfolio-os.portfolio-snapshot.v2"
    assert snapshot["reportingCurrency"] == "GBP"
    assert snapshot["dataQuality"] == "verified"

    account = snapshot["accountPerformance"]
    open_position = snapshot["openPositionPerformance"]

    assert account["accountValue"]["value"] == 1300.0

    # Account-boundary capital is independent from open-position cost basis.
    assert account["netAccountContributions"]["value"] == 1000.0
    assert account["netDeposits"]["value"] == 1000.0

    assert open_position["openPositionCostBasis"]["value"] == 800.0
    assert (
        open_position["openPositionCostBasis"]["method"]
        == "trading212_account_summary.investments.totalCost"
    )
    assert open_position["openPositionCostBasis"]["value"] != account["netAccountContributions"]["value"]

    # Lifetime monetary return is account value minus net account contributions.
    assert account["totalReturn"]["value"] == 300.0
    assert account["totalReturn"]["method"] == "accountValue_minus_netAccountContributions"

    # Broker open/realized P&L fields remain distinct from lifetime account return.
    assert open_position["realizedProfitLoss"]["value"] == 50.0
    assert open_position["unrealizedProfitLoss"]["value"] == 100.0
    assert (
        open_position["realizedProfitLoss"]["value"]
        + open_position["unrealizedProfitLoss"]["value"]
        != account["totalReturn"]["value"]
    )

    # One £1,000 contribution exactly one year before a £1,300 terminal value
    # has an annualized money-weighted return of 30%.
    mwrr = account["moneyWeightedReturnAnnualized"]
    assert mwrr["method"] == "XIRR_account_boundary_cash_flows_plus_terminal_account_value_annualized"
    assert mwrr["value"] == pytest.approx(0.30, rel=1e-9, abs=1e-9)

    # TWR must not be fabricated without valuations at external-flow boundaries.
    twr = account["timeWeightedReturn"]
    assert twr["value"] is None
    assert twr["confidence"] == "unavailable"
    assert twr["completeness"] == "incomplete"
    assert twr["reason"] == "requires_portfolio_valuations_at_each_external_cash_flow_boundary"


def test_account_cash_is_derived_from_balance_sheet_identity():
    snapshot = _build()

    cash = snapshot["cash"]
    reconciliation = snapshot["reconciliation"]

    # 1300 total account value - 900 invested value = 400 account cash.
    # Broker cash sub-fields are intentionally not blindly summed.
    assert cash["accountCashValue"]["value"] == 400.0
    assert cash["accountCashValue"]["method"] == "accountValue_minus_investedValue"

    assert cash["availableToTrade"] == 350.0
    assert cash["reservedForOrders"] == 50.0
    assert cash["inPies"] == 100.0

    assert (
        reconciliation["accountValueVsInvestedPlusCash"]["withinTolerance"]
        is True
    )


def test_unknown_transaction_type_propagates_fail_closed_to_snapshot():
    unknown = {
        "type": "MYSTERY_EVENT",
        "amount": 1000.0,
        "currency": "GBP",
        "dateTime": "2025-01-01T00:00:00+00:00",
        "reference": "mystery-1",
    }

    snapshot = _build(transactions=[unknown])

    account = snapshot["accountPerformance"]

    assert snapshot["dataQuality"] == "partial"
    assert account["netAccountContributions"]["value"] is None
    assert account["totalReturn"]["value"] is None
    assert account["moneyWeightedReturnAnnualized"]["value"] is None

    assert (
        account["moneyWeightedReturnAnnualized"]["reason"]
        == "transaction_history_incomplete_or_unclassified"
    )

    assert snapshot["historyCoverage"]["transactionsComplete"] is False
    assert snapshot["historyCoverage"]["unknownTransactionTypes"] == [
        "MYSTERY_EVENT"
    ]


def test_provider_incomplete_transaction_history_cannot_clear_account_returns():
    snapshot = _build(
        transactions=[_deposit()],
        transactions_complete=False,
    )

    account = snapshot["accountPerformance"]

    assert snapshot["dataQuality"] == "partial"
    assert account["netAccountContributions"]["value"] is None
    assert account["totalReturn"]["value"] is None
    assert account["moneyWeightedReturnAnnualized"]["value"] is None
    assert snapshot["historyCoverage"]["transactionsComplete"] is False


def test_missing_required_account_summary_fields_raise():
    bad_summary = {
        "currency": "GBP",
        "totalValue": 1000.0,
        "cash": {},
    }

    with pytest.raises(AccountingError):
        _build(account_summary=bad_summary)
