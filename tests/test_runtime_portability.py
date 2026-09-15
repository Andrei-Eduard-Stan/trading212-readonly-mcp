import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "src" / "server.py"
UNIT = ROOT / "deploy" / "portfolio-mcp.service"
VARS = ROOT / "deploy" / "ansible" / "group_vars" / "all.yml"
MCP_TASKS = (
    ROOT
    / "deploy"
    / "ansible"
    / "roles"
    / "portfolio_mcp"
    / "tasks"
    / "main.yml"
)
BOOTSTRAP = ROOT / "bootstrap.sh"
RESTORE = ROOT / "scripts" / "restore_from_kit.sh"


def test_server_runtime_identity_is_environment_backed():
    text = SERVER.read_text(encoding="utf-8")

    assert 'os.environ.get(' in text
    assert '"PORTFOLIO_PUBLIC_HOST"' in text
    assert '"PORTFOLIO_RESOURCE_URL"' in text
    assert '"PORTFOLIO_AUTH0_DOMAIN"' in text
    assert '"PORTFOLIO_AUTH0_CLIENT_ID"' in text
    assert '"PORTFOLIO_REQUIRED_SCOPE"' in text


def test_resource_url_is_independently_configurable_from_public_host():
    text = SERVER.read_text(encoding="utf-8")

    resource_block = text[
        text.index("RESOURCE_URL = os.environ.get("):
        text.index("AUTH0_DOMAIN = os.environ.get(")
    ]

    assert '"PORTFOLIO_RESOURCE_URL"' in resource_block
    assert "PUBLIC_HOST" not in resource_block


def test_systemd_consumes_managed_runtime_environment():
    unit = UNIT.read_text(encoding="utf-8")
    vars_text = VARS.read_text(encoding="utf-8")

    assert "EnvironmentFile=-/etc/portfolio-hub/portfolio-mcp.env" in unit
    assert (
        "portfolio_runtime_env_file: "
        "/etc/portfolio-hub/portfolio-mcp.env"
    ) in vars_text


def test_runtime_environment_changes_trigger_controlled_restart():
    text = MCP_TASKS.read_text(encoding="utf-8")

    assert "Write non-secret Portfolio MCP runtime configuration" in text
    assert "portfolio_runtime_env_copy" in text
    assert (
        "(portfolio_runtime_env_copy.changed | default(false))"
        in text
    )


def test_bootstrap_supports_isolated_dr_identity():
    text = BOOTSTRAP.read_text(encoding="utf-8")

    assert "--public-host" in text
    assert "--tailscale-hostname" in text
    assert "--resource-url" in text
    assert "portfolio_public_host=$PUBLIC_HOST_OVERRIDE" in text
    assert (
        "portfolio_tailscale_expected_hostname="
        "$TAILSCALE_HOSTNAME_OVERRIDE"
    ) in text
    assert "portfolio_resource_url=$RESOURCE_URL_OVERRIDE" in text


def test_bootstrap_keeps_public_host_and_resource_url_independent():
    text = BOOTSTRAP.read_text(encoding="utf-8")

    assert 'PUBLIC_HOST_OVERRIDE=""' in text
    assert 'RESOURCE_URL_OVERRIDE=""' in text

    assert (
        'if [ -n "$RESOURCE_URL_OVERRIDE" ]; then'
        in text
    )


def test_blank_host_restore_forwards_dr_identity_overrides():
    text = RESTORE.read_text(encoding="utf-8")

    assert "--public-host" in text
    assert "--tailscale-hostname" in text
    assert "--resource-url" in text

    assert '"$PUBLIC_HOST_OVERRIDE"' in text
    assert '"$TAILSCALE_HOSTNAME_OVERRIDE"' in text
    assert '"$RESOURCE_URL_OVERRIDE"' in text
    assert '"$REPO_DIR/bootstrap.sh" "${BOOTSTRAP_ARGS[@]}"' in text


def test_network_role_accepts_configured_dr_identity():
    network_tasks = (
        ROOT
        / "deploy"
        / "ansible"
        / "roles"
        / "portfolio_network"
        / "tasks"
        / "main.yml"
    ).read_text(encoding="utf-8")

    assert (
        'portfolio_tailscale_expected_dns_name == '
        '(portfolio_public_host ~ ".")'
        in network_tasks
    )

    assert (
        'portfolio_tailscale_expected_hostname == "portfolio-hub"'
        not in network_tasks
    )

    assert (
        'portfolio_tailscale_expected_dns_name == '
        '"portfolio-hub.tail894a11.ts.net."'
        not in network_tasks
    )

def test_server_applies_runtime_identity_overrides():
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")

    env.update(
        {
            "PORTFOLIO_PUBLIC_HOST": (
                "portfolio-hub-drtest.tail894a11.ts.net"
            ),
            "PORTFOLIO_RESOURCE_URL": (
                "https://portfolio-hub.tail894a11.ts.net/mcp"
            ),
            "PORTFOLIO_AUTH0_DOMAIN": "dr-test.example.auth0.com",
            "PORTFOLIO_AUTH0_CLIENT_ID": "dr-test-client",
            "PORTFOLIO_REQUIRED_SCOPE": "portfolio:read:test",
        }
    )

    code = """
import json
import server

print(
    json.dumps(
        {
            "public_host": server.PUBLIC_HOST,
            "resource_url": server.RESOURCE_URL,
            "auth0_domain": server.AUTH0_DOMAIN,
            "auth0_issuer": server.AUTH0_ISSUER,
            "auth0_jwks_url": server.AUTH0_JWKS_URL,
            "auth0_client_id": server.AUTH0_CLIENT_ID,
            "required_scope": server.REQUIRED_SCOPE,
        }
    )
)
"""

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    values = json.loads(result.stdout)

    assert (
        values["public_host"]
        == "portfolio-hub-drtest.tail894a11.ts.net"
    )
    assert (
        values["resource_url"]
        == "https://portfolio-hub.tail894a11.ts.net/mcp"
    )
    assert values["auth0_domain"] == "dr-test.example.auth0.com"
    assert (
        values["auth0_issuer"]
        == "https://dr-test.example.auth0.com/"
    )
    assert (
        values["auth0_jwks_url"]
        == "https://dr-test.example.auth0.com/.well-known/jwks.json"
    )
    assert values["auth0_client_id"] == "dr-test-client"
    assert values["required_scope"] == "portfolio:read:test"

