from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable


class Trading212Error(RuntimeError):
    pass


class Trading212Client:
    """GET-only Trading 212 provider adapter for Portfolio OS.

    No POST/DELETE/order-execution/Pie-write methods exist in this class.
    """

    BASE_URL = "https://live.trading212.com/api/v0"

    TTL_ACCOUNT_SUMMARY = 5.5
    TTL_POSITIONS = 2.0
    TTL_PENDING_ORDERS = 5.0
    TTL_PIES = 60.0
    TTL_PIE_DETAIL = 300.0
    TTL_INSTRUMENTS = 3600.0
    TTL_EXCHANGES = 3600.0
    TTL_TRANSACTIONS = 300.0
    TTL_DIVIDENDS = 900.0
    TTL_HISTORICAL_ORDERS = 900.0
    TTL_REPORTS = 60.0

    def __init__(
        self,
        api_key_file: str = "/etc/portfolio-hub/trading212_api_key",
        api_secret_file: str = "/etc/portfolio-hub/trading212_api_secret",
        timeout: int = 20,
        cache_dir: str | None = "/var/lib/portfolio-hub/cache/trading212",
        max_429_retries: int = 2,
    ) -> None:
        self.api_key_file = Path(api_key_file)
        self.api_secret_file = Path(api_secret_file)
        self.timeout = timeout
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.max_429_retries = max_429_retries
        self._memory_cache: dict[str, tuple[float, Any]] = {}

    def _read_credentials(self) -> tuple[str, str]:
        key = self.api_key_file.read_text(encoding="utf-8").strip()
        secret = self.api_secret_file.read_text(encoding="utf-8").strip()
        if not key:
            raise Trading212Error("Trading 212 API key is empty.")
        if not secret:
            raise Trading212Error("Trading 212 API secret is empty.")
        return key, secret

    def _authorization_header(self) -> str:
        key, secret = self._read_credentials()
        encoded = base64.b64encode(f"{key}:{secret}".encode("utf-8")).decode("ascii")
        return f"Basic {encoded}"

    def _url_for(self, path: str, params: dict[str, Any] | None = None) -> str:
        if path.startswith("https://"):
            url = path
        elif path.startswith("/api/v0/"):
            url = f"https://live.trading212.com{path}"
        else:
            url = f"{self.BASE_URL}{path}"
        if params:
            clean = {k: v for k, v in params.items() if v is not None}
            if clean:
                separator = "&" if "?" in url else "?"
                url += separator + urllib.parse.urlencode(clean)
        return url

    @staticmethod
    def _retry_delay(headers: Any, attempt: int) -> float:
        retry_after = headers.get("Retry-After") if headers else None
        if retry_after:
            try:
                return max(0.0, min(float(retry_after), 65.0))
            except ValueError:
                pass
        reset = headers.get("x-ratelimit-reset") if headers else None
        if reset:
            try:
                # Docs define x-ratelimit-reset as a Unix timestamp.
                return max(0.0, min(float(reset) - time.time() + 0.25, 65.0))
            except ValueError:
                pass
        return min(2.0 ** attempt, 10.0)

    def _get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | list[Any]:
        url = self._url_for(path, params)
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Authorization": self._authorization_header(),
                "Accept": "application/json",
                "User-Agent": "Portfolio-OS/0.3",
            },
        )

        for attempt in range(self.max_429_retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt < self.max_429_retries:
                    time.sleep(self._retry_delay(exc.headers, attempt))
                    continue
                body = exc.read().decode("utf-8", errors="replace")
                raise Trading212Error(
                    f"Trading 212 returned HTTP {exc.code}: {body[:500]}"
                ) from exc
            except urllib.error.URLError as exc:
                raise Trading212Error(
                    f"Trading 212 network error: {exc.reason}"
                ) from exc

        raise Trading212Error("Trading 212 request failed after retries.")

    def _cached(self, key: str, ttl: float, fetcher: Callable[[], Any]) -> Any:
        now = time.monotonic()
        cached = self._memory_cache.get(key)
        if cached is not None and (now - cached[0]) < ttl:
            return cached[1]
        value = fetcher()
        self._memory_cache[key] = (time.monotonic(), value)
        return value

    def _persistent_path(self, key: str) -> Path | None:
        if self.cache_dir is None:
            return None
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in key)
        return self.cache_dir / f"{safe}.json"

    def _read_persistent(self, key: str, ttl: float) -> Any | None:
        path = self._persistent_path(key)
        if path is None:
            return None
        try:
            if not path.exists() or (time.time() - path.stat().st_mtime) >= ttl:
                return None
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None

    def _write_persistent(self, key: str, value: Any) -> None:
        path = self._persistent_path(key)
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix(path.suffix + ".tmp")
            temp.write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8")
            os.replace(temp, path)
        except OSError:
            # Caching is an optimization; a cache permission problem must not
            # silently corrupt or replace provider data.
            return

    def _cached_persistent(
        self,
        key: str,
        ttl: float,
        fetcher: Callable[[], Any],
    ) -> Any:
        memory = self._memory_cache.get(key)
        now = time.monotonic()
        if memory is not None and (now - memory[0]) < ttl:
            return memory[1]
        disk = self._read_persistent(key, ttl)
        if disk is not None:
            self._memory_cache[key] = (time.monotonic(), disk)
            return disk
        value = fetcher()
        self._memory_cache[key] = (time.monotonic(), value)
        self._write_persistent(key, value)
        return value

    def _all_pages(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        first_params = dict(params or {})
        first_params.setdefault("limit", 50)
        page = self._get(path, first_params)
        if not isinstance(page, dict) or not isinstance(page.get("items"), list):
            raise Trading212Error(f"Unexpected paginated response for {path}.")

        items: list[dict[str, Any]] = []
        page_count = 0
        seen_paths: set[str] = set()
        while True:
            page_count += 1
            page_items = page.get("items")
            if not isinstance(page_items, list):
                raise Trading212Error(f"Malformed paginated response for {path}.")
            for item in page_items:
                if isinstance(item, dict):
                    items.append(item)

            next_path = page.get("nextPagePath")
            if not next_path:
                break
            if not isinstance(next_path, str):
                raise Trading212Error(f"Malformed nextPagePath for {path}.")
            if next_path in seen_paths:
                raise Trading212Error(f"Pagination loop detected for {path}.")
            seen_paths.add(next_path)

            # Trading 212 may return nextPagePath either as a full API path
            # or, on some live endpoints, as only the query string.
            if next_path.startswith(("https://", "/")):
                request_path = next_path
            elif next_path.startswith("?"):
                request_path = f"{path}{next_path}"
            elif "=" in next_path:
                request_path = f"{path}?{next_path}"
            else:
                raise Trading212Error(
                    f"Malformed nextPagePath for {path}: {next_path!r}"
                )

            page = self._get(request_path)
            if not isinstance(page, dict):
                raise Trading212Error(f"Unexpected next-page response for {path}.")

        # Stable de-duplication protects accounting against overlapping pages or
        # repeated upstream records.
        deduped: list[dict[str, Any]] = []
        seen_items: set[str] = set()
        for item in items:
            canonical = json.dumps(item, sort_keys=True, separators=(",", ":"))
            if canonical in seen_items:
                continue
            seen_items.add(canonical)
            deduped.append(item)

        return {
            "items": deduped,
            "complete": True,
            "pageCount": page_count,
            "itemCount": len(deduped),
            "fetchedAtEpoch": time.time(),
        }

    # Account / portfolio -------------------------------------------------

    def get_account_summary(self) -> dict[str, Any]:
        def fetch() -> dict[str, Any]:
            data = self._get("/equity/account/summary")
            if not isinstance(data, dict):
                raise Trading212Error("Unexpected account-summary response.")
            return data
        return self._cached("account_summary", self.TTL_ACCOUNT_SUMMARY, fetch)

    def get_cash_balance(self) -> dict[str, Any]:
        summary = self.get_account_summary()
        cash = summary.get("cash")
        if not isinstance(cash, dict):
            raise Trading212Error("Account summary contains no cash object.")
        return {"currency": summary.get("currency"), "cash": cash}

    def get_current_positions(self) -> list[dict[str, Any]]:
        def fetch() -> list[dict[str, Any]]:
            data = self._get("/equity/positions")
            if not isinstance(data, list):
                raise Trading212Error("Unexpected positions response.")
            return [x for x in data if isinstance(x, dict)]
        return self._cached("positions", self.TTL_POSITIONS, fetch)

    # Metadata ------------------------------------------------------------

    def get_instruments_metadata(self) -> list[dict[str, Any]]:
        def fetch() -> list[dict[str, Any]]:
            data = self._get("/equity/metadata/instruments")
            if not isinstance(data, list):
                raise Trading212Error("Unexpected instruments metadata response.")
            return [x for x in data if isinstance(x, dict)]
        return self._cached_persistent("instruments", self.TTL_INSTRUMENTS, fetch)

    def get_exchanges_metadata(self) -> list[dict[str, Any]]:
        def fetch() -> list[dict[str, Any]]:
            data = self._get("/equity/metadata/exchanges")
            if not isinstance(data, list):
                raise Trading212Error("Unexpected exchanges metadata response.")
            return [x for x in data if isinstance(x, dict)]
        return self._cached_persistent("exchanges", self.TTL_EXCHANGES, fetch)

    # Orders — GET only ---------------------------------------------------

    def get_pending_orders(self) -> list[dict[str, Any]]:
        def fetch() -> list[dict[str, Any]]:
            data = self._get("/equity/orders")
            if not isinstance(data, list):
                raise Trading212Error("Unexpected pending-orders response.")
            return [x for x in data if isinstance(x, dict)]
        return self._cached("pending_orders", self.TTL_PENDING_ORDERS, fetch)

    def get_order(self, order_id: int) -> dict[str, Any]:
        data = self._get(f"/equity/orders/{order_id}")
        if not isinstance(data, dict):
            raise Trading212Error("Unexpected order response.")
        return data

    # Historical — existing one-page audit methods -----------------------

    def get_historical_orders(
        self,
        limit: int = 50,
        ticker: str | None = None,
        cursor: int | None = None,
    ) -> dict[str, Any]:
        data = self._get(
            "/equity/history/orders",
            {"limit": min(max(limit, 1), 50), "ticker": ticker, "cursor": cursor},
        )
        if not isinstance(data, dict):
            raise Trading212Error("Unexpected historical-orders response.")
        return data

    def get_dividends(
        self,
        limit: int = 50,
        ticker: str | None = None,
        cursor: int | None = None,
    ) -> dict[str, Any]:
        data = self._get(
            "/equity/history/dividends",
            {"limit": min(max(limit, 1), 50), "ticker": ticker, "cursor": cursor},
        )
        if not isinstance(data, dict):
            raise Trading212Error("Unexpected dividends response.")
        return data

    def get_transactions(
        self,
        limit: int = 50,
        cursor: str | None = None,
        time: str | None = None,
    ) -> dict[str, Any]:
        data = self._get(
            "/equity/history/transactions",
            {"limit": min(max(limit, 1), 50), "cursor": cursor, "time": time},
        )
        if not isinstance(data, dict):
            raise Trading212Error("Unexpected transactions response.")
        return data

    # Complete-history accounting methods --------------------------------

    def get_all_transactions(self, force_refresh: bool = False) -> dict[str, Any]:
        key = "transactions_all"
        if force_refresh:
            self._memory_cache.pop(key, None)
            path = self._persistent_path(key)
            if path:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
        return self._cached_persistent(
            key,
            self.TTL_TRANSACTIONS,
            lambda: self._all_pages("/equity/history/transactions"),
        )

    def get_all_dividends(self, force_refresh: bool = False) -> dict[str, Any]:
        key = "dividends_all"
        if force_refresh:
            self._memory_cache.pop(key, None)
            path = self._persistent_path(key)
            if path:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
        return self._cached_persistent(
            key,
            self.TTL_DIVIDENDS,
            lambda: self._all_pages("/equity/history/dividends"),
        )

    def get_all_historical_orders(self, force_refresh: bool = False) -> dict[str, Any]:
        key = "historical_orders_all"
        if force_refresh:
            self._memory_cache.pop(key, None)
            path = self._persistent_path(key)
            if path:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
        return self._cached_persistent(
            key,
            self.TTL_HISTORICAL_ORDERS,
            lambda: self._all_pages("/equity/history/orders"),
        )

    def get_generated_reports(self) -> list[dict[str, Any]]:
        def fetch() -> list[dict[str, Any]]:
            data = self._get("/equity/history/exports")
            if not isinstance(data, list):
                raise Trading212Error("Unexpected reports response.")
            return [x for x in data if isinstance(x, dict)]
        return self._cached("generated_reports", self.TTL_REPORTS, fetch)

    # Pies — GET only, deprecated upstream --------------------------------

    def get_pies(self) -> list[dict[str, Any]]:
        def fetch() -> list[dict[str, Any]]:
            data = self._get("/equity/pies")
            if not isinstance(data, list):
                raise Trading212Error("Unexpected pies response.")
            return [x for x in data if isinstance(x, dict)]
        return self._cached_persistent("pies", self.TTL_PIES, fetch)

    def get_pie(self, pie_id: int) -> dict[str, Any]:
        key = f"pie_{pie_id}"
        def fetch() -> dict[str, Any]:
            data = self._get(f"/equity/pies/{pie_id}")
            if not isinstance(data, dict):
                raise Trading212Error("Unexpected pie response.")
            return data
        return self._cached_persistent(key, self.TTL_PIE_DETAIL, fetch)
