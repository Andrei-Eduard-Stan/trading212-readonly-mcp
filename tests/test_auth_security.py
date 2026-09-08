import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

import jwt

import server


ROOT = Path(__file__).resolve().parents[1]
SERVER_SOURCE = ROOT / "src" / "server.py"


def _valid_claims(**overrides):
    claims = {
        "exp": 2_000_000_000,
        "iat": 1_900_000_000,
        "iss": server.AUTH0_ISSUER,
        "aud": server.RESOURCE_URL,
        "sub": "auth0|test-user",
        "azp": server.AUTH0_CLIENT_ID,
        "scope": "portfolio:read offline_access",
    }
    claims.update(overrides)
    return claims


def _verifier():
    verifier = server.Auth0TokenVerifier()
    verifier.jwks_client = SimpleNamespace(
        get_signing_key_from_jwt=lambda token: SimpleNamespace(key="test-key")
    )
    return verifier


def test_valid_auth0_token_is_accepted(monkeypatch):
    verifier = _verifier()

    monkeypatch.setattr(
        server.jwt,
        "decode",
        lambda *args, **kwargs: _valid_claims(),
    )

    result = asyncio.run(verifier.verify_token("test-token"))

    assert result is not None
    assert result.client_id == server.AUTH0_CLIENT_ID
    assert result.resource == server.RESOURCE_URL
    assert result.subject == "auth0|test-user"
    assert result.scopes == ["portfolio:read", "offline_access"]


def test_wrong_authorized_party_is_rejected(monkeypatch):
    verifier = _verifier()

    monkeypatch.setattr(
        server.jwt,
        "decode",
        lambda *args, **kwargs: _valid_claims(azp="wrong-client"),
    )

    result = asyncio.run(verifier.verify_token("test-token"))

    assert result is None


def test_non_string_scope_claim_is_rejected(monkeypatch):
    verifier = _verifier()

    monkeypatch.setattr(
        server.jwt,
        "decode",
        lambda *args, **kwargs: _valid_claims(scope=["portfolio:read"]),
    )

    result = asyncio.run(verifier.verify_token("test-token"))

    assert result is None


def test_jwt_validation_errors_fail_closed(monkeypatch):
    verifier = _verifier()

    def reject(*args, **kwargs):
        raise jwt.InvalidTokenError("invalid")

    monkeypatch.setattr(server.jwt, "decode", reject)

    result = asyncio.run(verifier.verify_token("bad-token"))

    assert result is None


def test_jwt_decode_contract_is_rs256_issuer_and_resource_bound(monkeypatch):
    verifier = _verifier()
    captured = {}

    def decode(token, key, **kwargs):
        captured.update(kwargs)
        return _valid_claims()

    monkeypatch.setattr(server.jwt, "decode", decode)

    result = asyncio.run(verifier.verify_token("test-token"))

    assert result is not None
    assert captured["algorithms"] == ["RS256"]
    assert captured["audience"] == server.RESOURCE_URL
    assert captured["issuer"] == server.AUTH0_ISSUER
    assert captured["leeway"] == 30

    required = captured["options"]["require"]
    assert set(required) == {"exp", "iat", "iss", "aud", "sub"}


def test_mcp_auth_configuration_requires_portfolio_read():
    source = SERVER_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)

    mcp_assignment = next(
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "mcp"
            for target in node.targets
        )
    )

    mcp_call = mcp_assignment.value
    assert isinstance(mcp_call, ast.Call)

    auth_kw = next(
        kw for kw in mcp_call.keywords if kw.arg == "auth"
    )

    assert isinstance(auth_kw.value, ast.Call)

    auth_arguments = {
        kw.arg: ast.unparse(kw.value)
        for kw in auth_kw.value.keywords
    }

    assert auth_arguments["issuer_url"] == "AnyHttpUrl(AUTH0_ISSUER)"
    assert auth_arguments["resource_server_url"] == "AnyHttpUrl(RESOURCE_URL)"
    assert auth_arguments["required_scopes"] == "[REQUIRED_SCOPE]"

    assert server.REQUIRED_SCOPE == "portfolio:read"
    assert server.RESOURCE_URL == f"https://{server.PUBLIC_HOST}/mcp"


def test_oauth_discovery_metadata_is_consistent():
    metadata = server.AUTHORIZATION_SERVER_METADATA

    assert metadata["issuer"] == server.AUTH0_ISSUER
    assert metadata["jwks_uri"] == server.AUTH0_JWKS_URL
    assert metadata["authorization_endpoint"] == (
        f"https://{server.AUTH0_DOMAIN}/authorize"
    )
    assert metadata["token_endpoint"] == (
        f"https://{server.AUTH0_DOMAIN}/oauth/token"
    )

    assert metadata["response_types_supported"] == ["code"]
    assert "authorization_code" in metadata["grant_types_supported"]
    assert "refresh_token" in metadata["grant_types_supported"]
    assert metadata["code_challenge_methods_supported"] == ["S256"]
    assert "portfolio:read" in metadata["scopes_supported"]
    assert "offline_access" in metadata["scopes_supported"]
