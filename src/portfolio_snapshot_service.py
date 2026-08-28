from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any

from portfolio_accounting import build_portfolio_snapshot
from trading212 import Trading212Client, Trading212Error


_LONDON = ZoneInfo("Europe/London")


class PortfolioSnapshotService:
    """Read-only orchestration layer for canonical Portfolio OS accounting."""

    def __init__(self, client: Trading212Client) -> None:
        self.client = client

    @staticmethod
    def _now_london() -> str:
        return datetime.now(_LONDON).isoformat(timespec="seconds")

    @staticmethod
    def _optional_history(callable_) -> tuple[list[dict[str, Any]] | None, bool, str | None]:
        try:
            result = callable_()
        except Trading212Error as exc:
            return None, False, str(exc)
        if not isinstance(result, dict) or not isinstance(result.get("items"), list):
            return None, False, "unexpected_complete_history_shape"
        return (
            [item for item in result["items"] if isinstance(item, dict)],
            bool(result.get("complete")),
            None,
        )

    def get_snapshot(self) -> dict[str, Any]:
        as_of = self._now_london()

        # Essential current state. If either fails, no canonical current
        # portfolio snapshot can be claimed.
        account_summary = self.client.get_account_summary()
        positions = self.client.get_current_positions()

        transactions, transactions_complete, transactions_error = self._optional_history(
            self.client.get_all_transactions
        )
        dividends, dividends_complete, dividends_error = self._optional_history(
            self.client.get_all_dividends
        )
        historical_orders, historical_orders_complete, orders_error = self._optional_history(
            self.client.get_all_historical_orders
        )

        try:
            pending_orders = self.client.get_pending_orders()
            pending_orders_error = None
        except Trading212Error as exc:
            pending_orders = None
            pending_orders_error = str(exc)

        snapshot = build_portfolio_snapshot(
            account_summary=account_summary,
            positions=positions,
            transactions=transactions,
            transactions_complete=transactions_complete,
            dividends=dividends,
            dividends_complete=dividends_complete,
            historical_orders=historical_orders,
            historical_orders_complete=historical_orders_complete,
            pending_orders=pending_orders,
            as_of=as_of,
        )

        provider_errors = {
            name: value
            for name, value in {
                "transactions": transactions_error,
                "dividends": dividends_error,
                "historicalOrders": orders_error,
                "pendingOrders": pending_orders_error,
            }.items()
            if value is not None
        }
        snapshot["providerErrors"] = provider_errors
        if provider_errors and snapshot.get("dataQuality") == "verified":
            snapshot["dataQuality"] = "partial"

        snapshot["security"] = {
            "mode": "authenticated-read-only",
            "brokerMutationsExposed": False,
            "accountIdentifiersExposed": False,
        }
        return snapshot
