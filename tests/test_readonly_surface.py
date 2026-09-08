import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROVIDER = ROOT / "src" / "trading212.py"
SERVER = ROOT / "src" / "server.py"

EXPECTED_MCP_TOOLS = {
    "health_check",
    "get_account_summary",
    "get_cash_balance",
    "get_current_positions",
    "get_pies",
    "get_pie",
    "get_pending_orders",
    "get_historical_orders",
    "get_dividends",
    "get_transactions",
    "get_generated_reports",
    "find_instrument_metadata",
    "get_exchanges_metadata",
    "get_portfolio_snapshot",
}

FORBIDDEN_MUTATION_WORDS = {
    "buy",
    "sell",
    "place",
    "cancel",
    "modify",
    "execute",
    "delete",
    "update",
    "withdraw",
    "deposit",
    "write",
    "rebalance",
}


def _tree(path):
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _is_mcp_tool_decorator(node):
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "mcp"
        and node.func.attr == "tool"
    )


def test_trading212_public_provider_surface_is_get_only():
    tree = _tree(PROVIDER)

    client = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "Trading212Client"
    )

    public_methods = {
        node.name
        for node in client.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not node.name.startswith("_")
    }

    assert public_methods
    assert all(name.startswith("get_") for name in public_methods)

    for name in public_methods:
        lowered = name.lower()
        assert not any(word in lowered for word in FORBIDDEN_MUTATION_WORDS)


def test_all_explicit_http_requests_are_get():
    tree = _tree(PROVIDER)

    requests = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "Request"
    ]

    assert requests, "Expected at least one urllib Request construction."

    for request in requests:
        method = next(
            (kw.value for kw in request.keywords if kw.arg == "method"),
            None,
        )

        assert isinstance(method, ast.Constant)
        assert method.value == "GET"


def test_mcp_tool_surface_matches_reviewed_allowlist():
    tree = _tree(SERVER)

    tools = {}

    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        decorator = next(
            (d for d in node.decorator_list if _is_mcp_tool_decorator(d)),
            None,
        )

        if decorator is not None:
            tools[node.name] = decorator

    assert set(tools) == EXPECTED_MCP_TOOLS

    for name in tools:
        lowered = name.lower()
        assert not any(word in lowered for word in FORBIDDEN_MUTATION_WORDS)


def test_every_mcp_tool_is_annotated_read_only_and_non_destructive():
    tree = _tree(SERVER)

    checked = 0

    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        decorator = next(
            (d for d in node.decorator_list if _is_mcp_tool_decorator(d)),
            None,
        )

        if decorator is None:
            continue

        annotations_kw = next(
            (kw for kw in decorator.keywords if kw.arg == "annotations"),
            None,
        )

        assert annotations_kw is not None
        assert isinstance(annotations_kw.value, ast.Call)

        annotation_values = {
            kw.arg: kw.value.value
            for kw in annotations_kw.value.keywords
            if isinstance(kw.value, ast.Constant)
        }

        assert annotation_values.get("readOnlyHint") is True
        assert annotation_values.get("destructiveHint") is False

        checked += 1

    assert checked == len(EXPECTED_MCP_TOOLS)
