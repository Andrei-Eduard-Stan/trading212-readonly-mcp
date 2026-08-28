from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Iterable


class AccountingError(RuntimeError):
    pass


@dataclass(frozen=True)
class CashFlow:
    at: datetime
    amount: float
    reference: str
    kind: str


def _metric(
    value: float | None,
    *,
    currency: str | None = None,
    source: str,
    method: str,
    confidence: str,
    completeness: str = "complete",
    reason: str | None = None,
    validation: str | None = None,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "value": value,
        "source": source,
        "method": method,
        "confidence": confidence,
        "completeness": completeness,
    }
    if currency is not None:
        result["currency"] = currency
    if reason is not None:
        result["reason"] = reason
    if validation is not None:
        result["validation"] = validation
    if notes:
        result["notes"] = notes
    return result


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _dedupe(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        key = (
            item.get("reference"),
            item.get("id"),
            item.get("type"),
            item.get("dateTime") or item.get("paidOn") or item.get("filledAt"),
            item.get("amount"),
            item.get("currency"),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def classify_transactions(
    transactions: Iterable[dict[str, Any]],
    reporting_currency: str,
) -> dict[str, Any]:
    """Classify T212 account transactions conservatively.

    Trading 212 account transactions include capital flows and account
    activity. DEPOSIT, WITHDRAW and signed TRANSFER records can move capital
    across this account's boundary and therefore participate in account-level
    contribution and XIRR calculations. INTEREST_ON_FREE_CASH is account
    income, not contributed capital. Unknown types still fail closed.
    """

    unique = _dedupe(transactions)
    net_contributions = 0.0
    generic_fees = 0.0
    interest_received = 0.0
    cash_flows: list[CashFlow] = []
    unknown_types: set[str] = set()
    currency_mismatches: set[str] = set()
    malformed = 0

    for item in unique:
        tx_type = str(item.get("type") or "").upper().strip()
        amount = _as_float(item.get("amount"))
        currency = str(item.get("currency") or "").upper().strip()
        at = _parse_datetime(item.get("dateTime"))
        reference = str(item.get("reference") or item.get("id") or "")

        if tx_type not in {
            "DEPOSIT",
            "WITHDRAW",
            "FEE",
            "TRANSFER",
            "INTEREST_ON_FREE_CASH",
        }:
            unknown_types.add(tx_type or "<missing>")
            continue

        if amount is None:
            malformed += 1
            continue

        if currency and currency != reporting_currency:
            currency_mismatches.add(currency)
            continue

        magnitude = abs(amount)

        if tx_type == "DEPOSIT":
            if at is None:
                malformed += 1
                continue
            net_contributions += magnitude
            # Investor-perspective cash-flow convention for XIRR.
            cash_flows.append(CashFlow(at, -magnitude, reference, tx_type))
        elif tx_type == "WITHDRAW":
            if at is None:
                malformed += 1
                continue
            net_contributions -= magnitude
            cash_flows.append(CashFlow(at, magnitude, reference, tx_type))
        elif tx_type == "FEE":
            generic_fees += magnitude
        elif tx_type == "TRANSFER":
            # Trading 212 transaction history can use TRANSFER for capital
            # moving into or out of this specific account. Live reconciliation
            # against broker UI net deposits confirms inbound transfers must
            # participate in this account's contribution history.
            #
            # Positive amount  = capital enters this account.
            # Negative amount  = capital leaves this account.
            #
            # Investor-perspective XIRR convention:
            # money entering the account is a negative investor cash flow;
            # money leaving the account is a positive investor cash flow.
            if at is None:
                malformed += 1
                continue

            if amount > 0:
                net_contributions += amount
                cash_flows.append(
                    CashFlow(at, -amount, reference, tx_type)
                )
            elif amount < 0:
                net_contributions += amount
                cash_flows.append(
                    CashFlow(at, -amount, reference, tx_type)
                )
        elif tx_type == "INTEREST_ON_FREE_CASH":
            # Broker-paid income. It changes account value, but it is not
            # external investor capital and must not enter XIRR cash flows.
            interest_received += amount

    complete = not unknown_types and not currency_mismatches and malformed == 0

    return {
        "uniqueTransactions": unique,
        "transactionCount": len(unique),
        "netAccountContributions": net_contributions if complete else None,
        "genericAccountFees": generic_fees,
        "interestReceived": interest_received,
        "accountBoundaryCashFlows": cash_flows,
        "complete": complete,
        "unknownTypes": sorted(unknown_types),
        "currencyMismatches": sorted(currency_mismatches),
        "malformedCount": malformed,
    }


def aggregate_dividends(
    dividends: Iterable[dict[str, Any]],
    reporting_currency: str,
) -> dict[str, Any]:
    unique = _dedupe(dividends)
    total = 0.0
    malformed = 0
    currency_mismatches: set[str] = set()

    for item in unique:
        amount = _as_float(item.get("amount"))
        currency = str(item.get("currency") or "").upper().strip()
        if amount is None:
            malformed += 1
            continue
        if currency and currency != reporting_currency:
            currency_mismatches.add(currency)
            continue
        total += amount

    complete = malformed == 0 and not currency_mismatches
    return {
        "value": total if complete else None,
        "count": len(unique),
        "complete": complete,
        "malformedCount": malformed,
        "currencyMismatches": sorted(currency_mismatches),
    }


_FX_FEE_TYPES = {"CURRENCY_CONVERSION_FEE"}
_TRADING_FEE_TYPES = {
    "COMMISSION_TURNOVER",
    "FINRA_FEE",
    "TRANSACTION_FEE",
}
_TRADING_TAX_TYPES = {
    "FRENCH_TRANSACTION_TAX",
    "PTM_LEVY",
    "STAMP_DUTY",
    "STAMP_DUTY_RESERVE_TAX",
}
_KNOWN_ORDER_TAX_TYPES = _FX_FEE_TYPES | _TRADING_FEE_TYPES | _TRADING_TAX_TYPES


def aggregate_order_friction(
    historical_orders: Iterable[dict[str, Any]],
    reporting_currency: str,
) -> dict[str, Any]:
    """Aggregate detailed fees/taxes from HistoricalOrder.fill.walletImpact.taxes.

    We do not add generic account-transaction FEE records here, avoiding silent
    double counting across two upstream views.
    """

    fx_fees = 0.0
    trading_fees = 0.0
    trading_taxes = 0.0
    unknown_types: set[str] = set()
    currency_mismatches: set[str] = set()
    malformed = 0
    seen: set[tuple[Any, ...]] = set()

    for order in historical_orders:
        fill = order.get("fill")
        if not isinstance(fill, dict):
            continue
        wallet = fill.get("walletImpact")
        if not isinstance(wallet, dict):
            continue
        taxes = wallet.get("taxes")
        if not isinstance(taxes, list):
            continue

        fill_id = fill.get("id") or order.get("id")
        for tax in taxes:
            if not isinstance(tax, dict):
                malformed += 1
                continue
            name = str(tax.get("name") or "").upper().strip()
            quantity = _as_float(tax.get("quantity"))
            currency = str(tax.get("currency") or wallet.get("currency") or "").upper().strip()
            key = (fill_id, name, quantity, currency)
            if key in seen:
                continue
            seen.add(key)

            if not name or quantity is None:
                malformed += 1
                continue
            if currency and currency != reporting_currency:
                currency_mismatches.add(currency)
                continue
            if name not in _KNOWN_ORDER_TAX_TYPES:
                unknown_types.add(name)
                continue

            amount = abs(quantity)
            if name in _FX_FEE_TYPES:
                fx_fees += amount
            elif name in _TRADING_FEE_TYPES:
                trading_fees += amount
            else:
                trading_taxes += amount

    complete = not unknown_types and not currency_mismatches and malformed == 0
    return {
        "fxFeesPaid": fx_fees,
        "tradingFeesPaid": trading_fees,
        "tradingTaxesAndLevies": trading_taxes,
        "complete": complete,
        "unknownTypes": sorted(unknown_types),
        "currencyMismatches": sorted(currency_mismatches),
        "malformedCount": malformed,
    }


def _xnpv(rate: float, cash_flows: list[CashFlow]) -> float:
    if rate <= -1.0:
        raise ValueError("rate must be greater than -1")
    start = min(flow.at for flow in cash_flows)
    total = 0.0
    for flow in cash_flows:
        years = (flow.at - start).total_seconds() / (365.0 * 86400.0)
        total += flow.amount / ((1.0 + rate) ** years)
    return total


def xirr(cash_flows: Iterable[CashFlow]) -> float | None:
    """Annualized money-weighted return using actual dated cash flows.

    Returns None when a unique economically meaningful solution cannot be
    bracketed. The solver is deterministic and uses no external libraries.
    """

    flows = sorted(cash_flows, key=lambda f: f.at)
    if len(flows) < 2:
        return None
    if not any(f.amount < 0 for f in flows) or not any(f.amount > 0 for f in flows):
        return None

    # Find a sign-changing bracket. Rates span almost-total loss through very
    # high annualized returns without assuming a particular return regime.
    candidates = [
        -0.999999,
        -0.99,
        -0.95,
        -0.9,
        -0.75,
        -0.5,
        -0.25,
        0.0,
        0.05,
        0.1,
        0.25,
        0.5,
        1.0,
        2.0,
        5.0,
        10.0,
        50.0,
        100.0,
        1000.0,
    ]

    last_rate = candidates[0]
    try:
        last_value = _xnpv(last_rate, flows)
    except (OverflowError, ValueError):
        return None

    if abs(last_value) < 1e-10:
        return last_rate

    bracket: tuple[float, float] | None = None
    for rate in candidates[1:]:
        try:
            value = _xnpv(rate, flows)
        except (OverflowError, ValueError):
            continue
        if abs(value) < 1e-10:
            return rate
        if value * last_value < 0:
            bracket = (last_rate, rate)
            break
        last_rate, last_value = rate, value

    if bracket is None:
        return None

    low, high = bracket
    f_low = _xnpv(low, flows)
    for _ in range(200):
        mid = (low + high) / 2.0
        f_mid = _xnpv(mid, flows)
        if abs(f_mid) < 1e-10 or abs(high - low) < 1e-12:
            return mid
        if f_low * f_mid <= 0:
            high = mid
        else:
            low = mid
            f_low = f_mid
    return (low + high) / 2.0


def _close(a: float | None, b: float | None, tolerance: float = 0.02) -> bool | None:
    if a is None or b is None:
        return None
    return abs(a - b) <= tolerance


def build_portfolio_snapshot(
    *,
    account_summary: dict[str, Any],
    positions: list[dict[str, Any]],
    transactions: list[dict[str, Any]] | None,
    transactions_complete: bool,
    dividends: list[dict[str, Any]] | None,
    dividends_complete: bool,
    historical_orders: list[dict[str, Any]] | None,
    historical_orders_complete: bool,
    pending_orders: list[dict[str, Any]] | None,
    as_of: str,
) -> dict[str, Any]:
    """Build Portfolio OS's canonical deterministic account snapshot."""

    currency = str(account_summary.get("currency") or "").upper().strip()
    investments = account_summary.get("investments")
    cash_raw = account_summary.get("cash")
    if not currency or not isinstance(investments, dict) or not isinstance(cash_raw, dict):
        raise AccountingError("Account summary is missing required currency/investments/cash fields.")

    account_value = _as_float(account_summary.get("totalValue"))
    invested_value = _as_float(investments.get("currentValue"))
    open_cost = _as_float(investments.get("totalCost"))
    realized = _as_float(investments.get("realizedProfitLoss"))
    unrealized = _as_float(investments.get("unrealizedProfitLoss"))

    if account_value is None or invested_value is None:
        raise AccountingError("Account summary contains non-numeric totalValue/currentValue.")

    # Derive account cash from the broker's own balance sheet identity rather
    # than summing overlapping cash sub-fields (e.g. inPies may be a subset).
    account_cash_value = account_value - invested_value

    tx_result: dict[str, Any] | None = None
    if transactions is not None:
        tx_result = classify_transactions(transactions, currency)
        tx_result["complete"] = bool(tx_result["complete"] and transactions_complete)

    dividend_result: dict[str, Any] | None = None
    if dividends is not None:
        dividend_result = aggregate_dividends(dividends, currency)
        dividend_result["complete"] = bool(dividend_result["complete"] and dividends_complete)

    friction_result: dict[str, Any] | None = None
    if historical_orders is not None:
        friction_result = aggregate_order_friction(historical_orders, currency)
        friction_result["complete"] = bool(friction_result["complete"] and historical_orders_complete)

    net_contributions: float | None = None
    if tx_result is not None and tx_result["complete"]:
        net_contributions = _as_float(tx_result["netAccountContributions"])

    total_return: float | None = None
    if net_contributions is not None:
        total_return = account_value - net_contributions

    mwrr: float | None = None
    mwrr_reason: str | None = None
    if tx_result is None:
        mwrr_reason = "transaction_history_unavailable"
    elif not tx_result["complete"]:
        mwrr_reason = "transaction_history_incomplete_or_unclassified"
    else:
        flows = list(tx_result["accountBoundaryCashFlows"])
        terminal_at = _parse_datetime(as_of) or datetime.now(timezone.utc)
        flows.append(CashFlow(terminal_at, account_value, "terminal_value", "TERMINAL_VALUE"))
        mwrr = xirr(flows)
        if mwrr is None:
            mwrr_reason = "xirr_no_unique_or_bracketed_solution"

    dividends_value = (
        dividend_result["value"]
        if dividend_result is not None and dividend_result["complete"]
        else None
    )

    if friction_result is None:
        fx_fees = trading_fees = trading_taxes = None
    else:
        fx_fees = friction_result["fxFeesPaid"]
        trading_fees = friction_result["tradingFeesPaid"]
        trading_taxes = friction_result["tradingTaxesAndLevies"]

    generic_fees = tx_result["genericAccountFees"] if tx_result is not None else None
    interest_received = tx_result["interestReceived"] if tx_result is not None else None

    known_bridge: float | None = None
    bridge_difference: float | None = None
    bridge_notes: list[str] = []
    if total_return is not None and realized is not None and unrealized is not None:
        known_bridge = realized + unrealized
        if dividends_value is not None:
            known_bridge += dividends_value
        else:
            bridge_notes.append("Dividend history is unavailable or incomplete.")
        if interest_received is not None:
            known_bridge += interest_received
        else:
            bridge_notes.append("Interest-on-cash history is unavailable or incomplete.")
        if fx_fees is not None:
            known_bridge -= fx_fees
        if trading_fees is not None:
            known_bridge -= trading_fees
        if trading_taxes is not None:
            known_bridge -= trading_taxes
        if generic_fees is not None:
            # Expose, but do not subtract it here: it may overlap with detailed
            # order walletImpact taxes/fees and we refuse to double count.
            bridge_notes.append(
                "Generic FEE transactions are excluded from the return bridge because overlap with detailed order fees cannot be proven absent."
            )
        bridge_notes.append(
            "Dividend withholding is not exposed reliably by the current read-only public endpoints; no equality is forced."
        )
        bridge_difference = total_return - known_bridge

    cash_available = _as_float(cash_raw.get("availableToTrade"))
    reserved = _as_float(cash_raw.get("reservedForOrders"))
    in_pies = _as_float(cash_raw.get("inPies"))

    open_pnl_identity = None
    if invested_value is not None and open_cost is not None and unrealized is not None:
        open_pnl_identity = {
            "expectedUnrealizedProfitLoss": invested_value - open_cost,
            "reportedUnrealizedProfitLoss": unrealized,
            "withinTolerance": _close(invested_value - open_cost, unrealized),
            "tolerance": 0.02,
        }

    account_cash_candidates: dict[str, Any] = {
        "derivedAccountCash": account_cash_value,
        "availableToTrade": cash_available,
        "reservedForOrders": reserved,
        "inPies": in_pies,
        "note": "cash.inPies is not blindly added because broker cash sub-fields may overlap.",
    }

    total_return_identity = None
    if total_return is not None and net_contributions is not None:
        total_return_identity = {
            "lhsAccountValue": account_value,
            "rhsNetAccountContributionsPlusTotalReturn": net_contributions + total_return,
            "withinTolerance": _close(account_value, net_contributions + total_return),
            "tolerance": 0.02,
        }

    data_quality = "verified"
    limitations: list[str] = []
    if tx_result is None or not tx_result["complete"]:
        data_quality = "partial"
        limitations.append("Lifetime transaction history is incomplete or contains unclassified records; net contributions/total return/MWRR are not cleared.")
    if dividend_result is None or not dividend_result["complete"]:
        data_quality = "partial"
        limitations.append("Dividend aggregate is unavailable or incomplete.")
    if friction_result is None or not friction_result["complete"]:
        data_quality = "partial"
        limitations.append("Detailed order fee/tax aggregate is unavailable or incomplete.")
    limitations.append("Lifetime TWRR is unavailable without portfolio valuations at each account-boundary cash-flow boundary.")
    limitations.append(
        "Portfolio OS moneyWeightedReturnAnnualized is a calculated XIRR. "
        "Trading 212's broker-displayed Rate of Return is not exposed by the "
        "current public API and must not be assumed equivalent without "
        "independent reconciliation."
    )
    limitations.append("Dividend withholding is not reliably exposed by the current GET-only public API surface used by Portfolio OS.")

    return {
        "schemaVersion": "portfolio-os.portfolio-snapshot.v2",
        "asOf": as_of,
        "reportingCurrency": currency,
        "dataQuality": data_quality,
        "accountPerformance": {
            "accountValue": _metric(
                account_value,
                currency=currency,
                source="broker",
                method="trading212_account_summary.totalValue",
                confidence="verified",
            ),
            "netAccountContributions": _metric(
                net_contributions,
                currency=currency,
                source="derived",
                method="sum_account_boundary_capital_flows(DEPOSIT + signed_TRANSFER - WITHDRAW)",
                confidence="verified" if net_contributions is not None else "unavailable",
                completeness="complete" if net_contributions is not None else "incomplete",
                reason=None if net_contributions is not None else "complete_classified_transaction_history_required",
                validation="derived_from_complete_classified_transaction_history; broker_net_deposits_not_exposed_by_public_api",
                notes=[
                    "Measures capital crossing this Trading 212 account boundary.",
                    "Positive TRANSFER records can therefore count even when the movement is internal to a broader broker relationship.",
                    "This is NOT open-position cost basis.",
                ],
            ),
            "netDeposits": _metric(
                net_contributions,
                currency=currency,
                source="alias",
                method="alias_of_netAccountContributions",
                confidence="verified" if net_contributions is not None else "unavailable",
                completeness="complete" if net_contributions is not None else "incomplete",
                notes=[
                    "UI-friendly alias of Portfolio OS netAccountContributions.",
                    "Derived by Portfolio OS; not a broker-supplied API field.",
                ],
            ),
            "totalReturn": _metric(
                total_return,
                currency=currency,
                source="derived",
                method="accountValue_minus_netAccountContributions",
                confidence="verified" if total_return is not None else "unavailable",
                completeness="complete" if total_return is not None else "incomplete",
                reason=None if total_return is not None else "net_account_contributions_unavailable",
                notes=[
                    "Canonical lifetime account monetary P/L.",
                    "Do not substitute realizedProfitLoss or unrealizedProfitLoss for this metric.",
                ],
            ),
            "moneyWeightedReturnAnnualized": _metric(
                mwrr,
                source="calculated",
                method="XIRR_account_boundary_cash_flows_plus_terminal_account_value_annualized",
                confidence="calculated" if mwrr is not None else "unavailable",
                completeness="complete" if mwrr is not None else "incomplete",
                reason=mwrr_reason,
                validation="calculation_complete_but_not_equivalent_to_broker_display_without_independent_reconciliation",
                notes=[
                    "Annualized Portfolio OS XIRR calculated from dated account-boundary capital flows and terminal account value.",
                    "This is NOT broker-supplied Trading 212 Rate of Return.",
                    "Trading 212's displayed MAX Rate of Return is not exposed by the current public API.",
                    "Do not transform or force-match this value to a broker UI percentage.",
                ],
            ),
            "timeWeightedReturn": _metric(
                None,
                source="unavailable",
                method="TWRR",
                confidence="unavailable",
                completeness="incomplete",
                reason="requires_portfolio_valuations_at_each_external_cash_flow_boundary",
            ),
        },
        "openPositionPerformance": {
            "investedValue": _metric(
                invested_value,
                currency=currency,
                source="broker",
                method="trading212_account_summary.investments.currentValue",
                confidence="verified",
            ),
            "openPositionCostBasis": _metric(
                open_cost,
                currency=currency,
                source="broker_normalized",
                method="trading212_account_summary.investments.totalCost",
                confidence="verified",
                notes=[
                    "Trading 212's upstream field is named totalCost; Portfolio OS normalizes it to openPositionCostBasis.",
                    "This is NOT lifetime contributed capital or net deposits.",
                ],
            ),
            "unrealizedProfitLoss": _metric(
                unrealized,
                currency=currency,
                source="broker",
                method="trading212_account_summary.investments.unrealizedProfitLoss",
                confidence="verified",
                notes=["Relates to currently open investments; it is NOT total account return."],
            ),
            "realizedProfitLoss": _metric(
                realized,
                currency=currency,
                source="broker",
                method="trading212_account_summary.investments.realizedProfitLoss",
                confidence="verified",
                notes=["All-time realized trading P/L; it is not by itself lifetime account performance."],
            ),
        },
        "cash": {
            "accountCashValue": _metric(
                account_cash_value,
                currency=currency,
                source="derived",
                method="accountValue_minus_investedValue",
                confidence="verified",
            ),
            "availableToTrade": cash_available,
            "reservedForOrders": reserved,
            "inPies": in_pies,
        },
        "incomeAndFriction": {
            "dividendsReceived": _metric(
                dividends_value,
                currency=currency,
                source="calculated",
                method="sum_complete_deduplicated_dividend_history.amount",
                confidence="verified" if dividends_value is not None else "unavailable",
                completeness="complete" if dividends_value is not None else "incomplete",
            ),
            "interestReceived": _metric(
                interest_received,
                currency=currency,
                source="calculated",
                method="sum_account_transactions[type=INTEREST_ON_FREE_CASH]",
                confidence="verified" if tx_result is not None and tx_result["complete"] else "partial",
                completeness="complete" if tx_result is not None and tx_result["complete"] else "incomplete",
                reason=None if tx_result is not None and tx_result["complete"] else "complete_classified_transaction_history_required",
            ),
            "fxFeesPaid": _metric(
                fx_fees,
                currency=currency,
                source="calculated",
                method="sum_historical_order_walletImpact.taxes[CURRENCY_CONVERSION_FEE]",
                confidence="verified" if friction_result is not None and friction_result["complete"] else "partial",
                completeness="complete" if friction_result is not None and friction_result["complete"] else "incomplete",
            ),
            "tradingFeesPaid": _metric(
                trading_fees,
                currency=currency,
                source="calculated",
                method="sum_historical_order_walletImpact.taxes[COMMISSION_TURNOVER|FINRA_FEE|TRANSACTION_FEE]",
                confidence="verified" if friction_result is not None and friction_result["complete"] else "partial",
                completeness="complete" if friction_result is not None and friction_result["complete"] else "incomplete",
            ),
            "taxesOrWithholding": _metric(
                trading_taxes,
                currency=currency,
                source="calculated",
                method="sum_historical_order_walletImpact trading taxes/levies",
                confidence="partial",
                completeness="partial",
                reason="covers_trading_taxes_and_levies; dividend_withholding_not_reliably_exposed",
            ),
            "otherFees": _metric(
                generic_fees,
                currency=currency,
                source="calculated",
                method="sum_account_transactions[type=FEE]",
                confidence="partial",
                completeness="complete" if tx_result is not None and tx_result["complete"] else "incomplete",
                reason="reported_separately_to_avoid_unproven_double_count_with_order_walletImpact_fees",
            ),
        },
        "counts": {
            "positionCount": len(positions),
            "transactionCount": tx_result["transactionCount"] if tx_result is not None else None,
            "dividendCount": dividend_result["count"] if dividend_result is not None else None,
            "pendingOrderCount": len(pending_orders) if pending_orders is not None else None,
        },
        "reconciliation": {
            "accountValueVsInvestedPlusCash": {
                "accountValue": account_value,
                "investedValue": invested_value,
                "derivedAccountCash": account_cash_value,
                "withinTolerance": _close(account_value, invested_value + account_cash_value),
                "tolerance": 0.02,
            },
            "brokerCashFields": account_cash_candidates,
            "openPositionPnlIdentity": open_pnl_identity,
            "totalReturnIdentity": total_return_identity,
            "performanceMetricSemantics": {
                "portfolioOSMetric": "accountPerformance.moneyWeightedReturnAnnualized",
                "method": "annualized_XIRR",
                "brokerDisplayedRateOfReturnAvailableViaPublicApi": False,
                "brokerReconciliationStatus": "not_available_from_public_api",
                "notes": [
                    "Portfolio OS does not claim its calculated annualized XIRR is identical to Trading 212's displayed MAX Rate of Return.",
                    "No broker UI percentage is fabricated or reverse-engineered.",
                ],
            },
            "knownReturnComponents": {
                "knownComponentsNet": known_bridge,
                "differenceToTotalReturn": bridge_difference,
                "status": "diagnostic_only_not_forced_equality",
                "notes": bridge_notes,
            },
        },
        "historyCoverage": {
            "transactionsComplete": bool(transactions_complete and tx_result is not None and tx_result["complete"]),
            "dividendsComplete": bool(dividends_complete and dividend_result is not None and dividend_result["complete"]),
            "historicalOrdersComplete": bool(historical_orders_complete and friction_result is not None and friction_result["complete"]),
            "unknownTransactionTypes": tx_result["unknownTypes"] if tx_result is not None else [],
            "unknownOrderTaxTypes": friction_result["unknownTypes"] if friction_result is not None else [],
        },
        "limitations": limitations,
    }
