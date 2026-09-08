import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER_SOURCE = ROOT / "src" / "server.py"
SERVICE_FILE = ROOT / "deploy" / "portfolio-mcp.service"


def _service_directives():
    directives = {}
    in_service = False

    for raw_line in SERVICE_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()

        if line == "[Service]":
            in_service = True
            continue

        if line.startswith("[") and line.endswith("]"):
            if in_service:
                break
            continue

        if in_service and line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            directives.setdefault(key, []).append(value)

    return directives


def test_mcp_runtime_binds_only_to_loopback_port_8000():
    tree = ast.parse(SERVER_SOURCE.read_text(encoding="utf-8"))

    run_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "mcp"
        and node.func.attr == "run"
    ]

    assert len(run_calls) == 1

    kwargs = {
        kw.arg: kw.value.value
        for kw in run_calls[0].keywords
        if isinstance(kw.value, ast.Constant)
    }

    assert kwargs["transport"] == "streamable-http"
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 8000
    assert kwargs["stateless_http"] is True
    assert kwargs["json_response"] is True


def test_systemd_service_identity_and_execution_contract():
    directives = _service_directives()

    assert directives["User"] == ["portfolio"]
    assert directives["Group"] == ["portfolio"]
    assert directives["WorkingDirectory"] == ["/opt/portfolio-hub"]
    assert directives["UMask"] == ["0027"]
    assert directives["ExecStart"] == [
        "/opt/portfolio-hub/venv/bin/python /opt/portfolio-hub/server.py"
    ]


def test_systemd_hardening_and_write_boundary():
    directives = _service_directives()

    expected = {
        "NoNewPrivileges": "true",
        "PrivateTmp": "true",
        "ProtectSystem": "strict",
        "ProtectHome": "true",
        "ProtectKernelTunables": "true",
        "ProtectKernelModules": "true",
        "ProtectControlGroups": "true",
        "RestrictSUIDSGID": "true",
        "LockPersonality": "true",
    }

    for key, value in expected.items():
        assert directives[key] == [value]

    assert directives["ReadWritePaths"] == ["/var/lib/portfolio-hub"]
