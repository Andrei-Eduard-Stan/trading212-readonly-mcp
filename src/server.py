import os
import jwt
from datetime import datetime
from time import monotonic
from zoneinfo import ZoneInfo

from trading212 import Trading212Client, Trading212Error
from portfolio_snapshot_service import PortfolioSnapshotService

from jwt.exceptions import PyJWTError
from pydantic import AnyHttpUrl
from starlette.requests import Request
from starlette.responses import JSONResponse

from mcp.server import MCPServer
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import ToolAnnotations


DEFAULT_PUBLIC_HOST = "portfolio-hub.tail894a11.ts.net"
DEFAULT_RESOURCE_URL = "https://portfolio-hub.tail894a11.ts.net/mcp"
DEFAULT_AUTH0_DOMAIN = "dev-portfolio-os-mcp.uk.auth0.com"
DEFAULT_AUTH0_CLIENT_ID = "tpc_4JWsLVNpgaz5gg5F5XUNHK"
DEFAULT_REQUIRED_SCOPE = "portfolio:read"

PUBLIC_HOST = os.environ.get(
    "PORTFOLIO_PUBLIC_HOST",
    DEFAULT_PUBLIC_HOST,
)

RESOURCE_URL = os.environ.get(
    "PORTFOLIO_RESOURCE_URL",
    DEFAULT_RESOURCE_URL,
)

AUTH0_DOMAIN = os.environ.get(
    "PORTFOLIO_AUTH0_DOMAIN",
    DEFAULT_AUTH0_DOMAIN,
)

AUTH0_ISSUER = f"https://{AUTH0_DOMAIN}/"
AUTH0_JWKS_URL = f"https://{AUTH0_DOMAIN}/.well-known/jwks.json"

# Third-Party ChatGPT Portfolio OS
AUTH0_CLIENT_ID = os.environ.get(
    "PORTFOLIO_AUTH0_CLIENT_ID",
    DEFAULT_AUTH0_CLIENT_ID,
)

REQUIRED_SCOPE = os.environ.get(
    "PORTFOLIO_REQUIRED_SCOPE",
    DEFAULT_REQUIRED_SCOPE,
)


transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=[
        "127.0.0.1",
        "127.0.0.1:*",
        "localhost",
        "localhost:*",
        "[::1]",
        "[::1]:*",
        PUBLIC_HOST,
        f"{PUBLIC_HOST}:*",
    ],
    allowed_origins=[
        "http://127.0.0.1",
        "http://127.0.0.1:*",
        "http://localhost",
        "http://localhost:*",
        "http://[::1]",
        "http://[::1]:*",
        f"https://{PUBLIC_HOST}",
        f"https://{PUBLIC_HOST}:*",
    ],
)


class Auth0TokenVerifier(TokenVerifier):
    """Validate Auth0 RS256 access tokens intended for Portfolio OS."""

    def __init__(self) -> None:
        self.jwks_client = jwt.PyJWKClient(
            AUTH0_JWKS_URL,
            cache_keys=True,
            cache_jwk_set=True,
            lifespan=300,
            timeout=5,
        )

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            signing_key = self.jwks_client.get_signing_key_from_jwt(token)

            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=RESOURCE_URL,
                issuer=AUTH0_ISSUER,
                leeway=30,
                options={
                    "require": [
                        "exp",
                        "iat",
                        "iss",
                        "aud",
                        "sub",
                    ],
                },
            )

            # Auth0's default access-token profile identifies
            # the requesting OAuth client using the "azp" claim.
            if claims.get("azp") != AUTH0_CLIENT_ID:
                return None

            scope_claim = claims.get("scope", "")
            if not isinstance(scope_claim, str):
                return None

            scopes = [scope for scope in scope_claim.split() if scope]

            return AccessToken(
                token=token,
                client_id=AUTH0_CLIENT_ID,
                scopes=scopes,
                expires_at=int(claims["exp"]),
                resource=RESOURCE_URL,
                subject=str(claims["sub"]),
                claims=claims,
            )

        except (PyJWTError, ValueError, TypeError):
            # Fail closed on malformed, invalid, expired,
            # wrongly signed, wrong-audience, or wrong-issuer tokens.
            return None


mcp = MCPServer(
    "Portfolio OS",
    token_verifier=Auth0TokenVerifier(),
    auth=AuthSettings(
        issuer_url=AnyHttpUrl(AUTH0_ISSUER),
        resource_server_url=AnyHttpUrl(RESOURCE_URL),
        required_scopes=[REQUIRED_SCOPE],
    ),
)


AUTHORIZATION_SERVER_METADATA = {
    "issuer": AUTH0_ISSUER,
    "authorization_endpoint": f"https://{AUTH0_DOMAIN}/authorize",
    "token_endpoint": f"https://{AUTH0_DOMAIN}/oauth/token",
    "jwks_uri": AUTH0_JWKS_URL,
    "response_types_supported": ["code"],
    "grant_types_supported": [
        "authorization_code",
        "refresh_token",
    ],
    "code_challenge_methods_supported": ["S256"],
    "token_endpoint_auth_methods_supported": [
        "client_secret_post",
        "client_secret_basic",
    ],
    "scopes_supported": [
        "portfolio:read",
        "offline_access",
    ],
}


@mcp.custom_route(
    "/.well-known/oauth-authorization-server",
    methods=["GET", "HEAD"],
    name="oauth_authorization_server_metadata_root",
    include_in_schema=False,
)
@mcp.custom_route(
    "/.well-known/oauth-authorization-server/mcp",
    methods=["GET", "HEAD"],
    name="oauth_authorization_server_metadata_mcp",
    include_in_schema=False,
)
async def oauth_authorization_server_metadata(
    request: Request,
) -> JSONResponse:
    """Expose Auth0 discovery metadata for ChatGPT MCP compatibility."""
    return JSONResponse(AUTHORIZATION_SERVER_METADATA)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Portfolio OS Health Check",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=False,
    )
)
def health_check() -> dict[str, str]:
    """Return the health state of the Portfolio OS MCP server."""
    return {
        "service": "Portfolio OS",
        "status": "ok",
        "mode": "authenticated-read-only",
    }


# ---------------------------------------------------------------------------
# Trading 212 read-only provider
# ---------------------------------------------------------------------------

trading212 = Trading212Client()
portfolio_snapshot_service = PortfolioSnapshotService(trading212)

_LONDON_TZ = ZoneInfo("Europe/London")

# Trading 212 account summary is rate-limited. Reuse the same provider
# snapshot briefly so account-summary and cash tools can safely be called
# back-to-back without immediately generating another upstream request.
_SUMMARY_CACHE_SECONDS = 5.5
_summary_cache_data = None
_summary_cache_fetched_at = None
_summary_cache_monotonic = 0.0


def _london_now() -> str:
    return datetime.now(_LONDON_TZ).isoformat(timespec="seconds")


def _get_summary_snapshot():
    global _summary_cache_data
    global _summary_cache_fetched_at
    global _summary_cache_monotonic

    now = monotonic()

    if (
        _summary_cache_data is not None
        and _summary_cache_fetched_at is not None
        and (now - _summary_cache_monotonic) < _SUMMARY_CACHE_SECONDS
    ):
        return (
            _summary_cache_data,
            _summary_cache_fetched_at,
            True,
        )

    try:
        summary = trading212.get_account_summary()
    except Trading212Error as exc:
        raise RuntimeError(
            f"Trading 212 account-summary read failed: {exc}"
        ) from exc

    fetched_at = _london_now()

    _summary_cache_data = summary
    _summary_cache_fetched_at = fetched_at
    _summary_cache_monotonic = monotonic()

    return summary, fetched_at, False


@mcp.tool(
    annotations=ToolAnnotations(
        title="Trading 212 Account Summary — Balance / Open Positions",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def get_account_summary() -> dict:
    """Return normalized current broker balance and open-position P/L.

    IMPORTANT SEMANTICS:
    - openPositionCostBasis is the cost basis of CURRENT investments, not lifetime deposits.
    - unrealizedProfitLoss relates to CURRENT open investments, not lifetime account return.
    - realizedProfitLoss is realized trading P/L, not total lifetime account performance.
    - Use get_portfolio_snapshot for net account contributions, total account return and Portfolio OS annualized XIRR.
    """

    summary, fetched_at, cached = _get_summary_snapshot()
    investments = summary.get("investments")
    if not isinstance(investments, dict):
        raise RuntimeError("Trading 212 account summary did not contain investments.")

    return {
        "schemaVersion": "portfolio-os.account-summary.v2",
        "provider": "Trading 212",
        "environment": "live",
        "retrievedAt": fetched_at,
        "cached": cached,
        "reportingCurrency": summary.get("currency"),
        "data": {
            "currency": summary.get("currency"),
            "cash": summary.get("cash"),
            "investments": {
                "currentValue": investments.get("currentValue"),
                "openPositionCostBasis": investments.get("totalCost"),
                "realizedProfitLoss": investments.get("realizedProfitLoss"),
                "unrealizedProfitLoss": investments.get("unrealizedProfitLoss"),
            },
            "totalValue": summary.get("totalValue"),
        },
        "semantics": {
            "openPositionCostBasis": "Cost basis of currently open investments. NOT lifetime contributed capital or net deposits.",
            "unrealizedProfitLoss": "P/L on currently open investments. NOT total account return.",
            "realizedProfitLoss": "Realized trading P/L. NOT total account return by itself.",
            "accountPerformanceTool": "Use get_portfolio_snapshot for account-level totalReturn and moneyWeightedReturnAnnualized.",
        },
        "upstreamFieldMapping": {
            "investments.totalCost": "investments.openPositionCostBasis"
        },
    }

@mcp.tool(
    annotations=ToolAnnotations(
        title="Trading 212 Cash Balance",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def get_cash_balance() -> dict:
    """Return current broker cash fields. This is NOT lifetime deposits/net account contributions; use get_portfolio_snapshot for those accounting metrics."""

    summary, fetched_at, cached = _get_summary_snapshot()

    cash = summary.get("cash")

    if not isinstance(cash, dict):
        raise RuntimeError(
            "Trading 212 account summary did not contain a cash object."
        )

    return {
        "provider": "Trading 212",
        "environment": "live",
        "retrievedAt": fetched_at,
        "cached": cached,
        "reportingCurrency": summary.get("currency"),
        "data": cash,
    }


@mcp.tool(
    annotations=ToolAnnotations(
        title="Trading 212 Current Positions",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def get_current_positions() -> dict:
    """Return all current open Trading 212 positions."""

    try:
        positions = trading212.get_current_positions()
    except Trading212Error as exc:
        raise RuntimeError(
            f"Trading 212 positions read failed: {exc}"
        ) from exc

    return {
        "provider": "Trading 212",
        "environment": "live",
        "retrievedAt": _london_now(),
        "positionCount": len(positions),
        "data": positions,
    }


# ---------------------------------------------------------------------------
# Full Trading 212 read surface
# ---------------------------------------------------------------------------

def _provider_envelope(data, **extra):
    result = {
        "provider": "Trading 212",
        "environment": "live",
        "retrievedAt": _london_now(),
        "data": data,
    }
    result.update(extra)
    return result


@mcp.tool(
    annotations=ToolAnnotations(
        title="Trading 212 Pies",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def get_pies() -> dict:
    """Return all Trading 212 Pies. This is read-only."""
    try:
        pies = trading212.get_pies()
    except Trading212Error as exc:
        raise RuntimeError(
            f"Trading 212 Pies read failed: {exc}"
        ) from exc

    return _provider_envelope(
        pies,
        pieCount=len(pies),
        upstreamStatus="deprecated-but-readable",
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Trading 212 Pie",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def get_pie(pie_id: int) -> dict:
    """Return one Trading 212 Pie by ID. This is read-only."""
    try:
        pie = trading212.get_pie(pie_id)
    except Trading212Error as exc:
        raise RuntimeError(
            f"Trading 212 Pie read failed: {exc}"
        ) from exc

    return _provider_envelope(
        pie,
        pieId=pie_id,
        upstreamStatus="deprecated-but-readable",
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Trading 212 Pending Orders",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def get_pending_orders() -> dict:
    """Return current pending Trading 212 orders. No order action is possible."""
    try:
        orders = trading212.get_pending_orders()
    except Trading212Error as exc:
        raise RuntimeError(
            f"Trading 212 pending-orders read failed: {exc}"
        ) from exc

    return _provider_envelope(
        orders,
        orderCount=len(orders),
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Trading 212 Historical Orders",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def get_historical_orders(
    limit: int = 50,
    ticker: str | None = None,
    cursor: int | None = None,
) -> dict:
    """Return historical Trading 212 orders, up to 50 per request."""
    try:
        history = trading212.get_historical_orders(
            limit=limit,
            ticker=ticker,
            cursor=cursor,
        )
    except Trading212Error as exc:
        raise RuntimeError(
            f"Trading 212 historical-orders read failed: {exc}"
        ) from exc

    return _provider_envelope(history)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Trading 212 Dividends",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def get_dividends(
    limit: int = 50,
    ticker: str | None = None,
    cursor: int | None = None,
) -> dict:
    """Return Trading 212 dividend history, up to 50 per request."""
    try:
        history = trading212.get_dividends(
            limit=limit,
            ticker=ticker,
            cursor=cursor,
        )
    except Trading212Error as exc:
        raise RuntimeError(
            f"Trading 212 dividend-history read failed: {exc}"
        ) from exc

    return _provider_envelope(history)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Trading 212 Transactions",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def get_transactions(
    limit: int = 50,
    cursor: str | None = None,
    time: str | None = None,
) -> dict:
    """Return Trading 212 transaction history, up to 50 per request."""
    try:
        history = trading212.get_transactions(
            limit=limit,
            cursor=cursor,
            time=time,
        )
    except Trading212Error as exc:
        raise RuntimeError(
            f"Trading 212 transaction-history read failed: {exc}"
        ) from exc

    return _provider_envelope(history)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Trading 212 Generated Reports",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def get_generated_reports() -> dict:
    """Return already-generated Trading 212 historical reports."""
    try:
        reports = trading212.get_generated_reports()
    except Trading212Error as exc:
        raise RuntimeError(
            f"Trading 212 reports read failed: {exc}"
        ) from exc

    return _provider_envelope(
        reports,
        reportCount=len(reports),
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Trading 212 Instrument Metadata",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def find_instrument_metadata(
    query: str,
    limit: int = 25,
) -> dict:
    """
    Search Trading 212 instrument metadata by ISIN, ticker or name.

    The full provider catalogue is large, so this tool returns matching
    records rather than dumping the entire catalogue.
    """
    try:
        instruments = trading212.get_instruments_metadata()
    except Trading212Error as exc:
        raise RuntimeError(
            f"Trading 212 instrument-metadata read failed: {exc}"
        ) from exc

    q = query.strip().casefold()

    if not q:
        raise ValueError("query must not be empty")

    matches = []

    for item in instruments:
        searchable = " ".join(
            str(item.get(field, ""))
            for field in (
                "ticker",
                "isin",
                "name",
                "currency",
            )
        ).casefold()

        if q in searchable:
            matches.append(item)

    safe_limit = min(max(limit, 1), 100)

    return _provider_envelope(
        matches[:safe_limit],
        query=query,
        totalMatches=len(matches),
        returnedMatches=min(
            len(matches),
            safe_limit,
        ),
        truncated=len(matches) > safe_limit,
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Trading 212 Exchange Metadata",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def get_exchanges_metadata() -> dict:
    """Return Trading 212 exchange metadata."""
    try:
        exchanges = trading212.get_exchanges_metadata()
    except Trading212Error as exc:
        raise RuntimeError(
            f"Trading 212 exchange-metadata read failed: {exc}"
        ) from exc

    return _provider_envelope(
        exchanges,
        exchangeCount=len(exchanges),
    )


# ---------------------------------------------------------------------------
# Canonical deterministic portfolio accounting
# ---------------------------------------------------------------------------

@mcp.tool(
    annotations=ToolAnnotations(
        title="Portfolio OS Canonical Portfolio Snapshot",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def get_portfolio_snapshot() -> dict:
    """Return Portfolio OS's canonical deterministic account snapshot.

    Use this tool for account-level accounting facts and performance semantics.
    Portfolio OS, not the LLM, derives net account contributions, total account
    monetary return and annualized XIRR from complete dated account-boundary cash flows.

    Distinctions enforced by this schema:
    - openPositionCostBasis != lifetime net account contributions
    - unrealizedProfitLoss != total account return
    - realizedProfitLoss + unrealizedProfitLoss is not assumed to equal total return
    - timeWeightedReturn is null unless sufficient valuation history exists

    The tool is authenticated and strictly read-only. It exposes no broker
    mutation, order execution, cancellation, withdrawal or Pie-write action.
    """
    return portfolio_snapshot_service.get_snapshot()


if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host="127.0.0.1",
        port=8000,
        stateless_http=True,
        json_response=True,
        transport_security=transport_security,
    )
