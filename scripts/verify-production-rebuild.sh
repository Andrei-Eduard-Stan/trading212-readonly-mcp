#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

EXPECTED_PYTHON="3.14.4"
LOCK="requirements.lock.txt"
LIVE_FREEZE="provenance/pip-freeze-live.txt"
HASH_MANIFEST="provenance/production-source-sha256.txt"

pass() {
    printf '[PASS] %s\n' "$1"
}

fail() {
    printf '[FAIL] %s\n' "$1" >&2
    exit 1
}

command -v uv >/dev/null 2>&1 || fail "uv is not installed"
command -v sha256sum >/dev/null 2>&1 || fail "sha256sum is not available"

[ -f "$LOCK" ] || fail "$LOCK is missing"
[ -f "$LIVE_FREEZE" ] || fail "$LIVE_FREEZE is missing"
[ -f "$HASH_MANIFEST" ] || fail "$HASH_MANIFEST is missing"

cmp -s "$LOCK" "$LIVE_FREEZE" || fail "requirements.lock.txt differs from captured production pip freeze"
pass "production dependency lock matches captured pip freeze"

sha256sum -c "$HASH_MANIFEST"
pass "production source hashes match captured baseline"

TMP_ROOT="$(mktemp -d -t t212-production-rebuild.XXXXXX)"
trap 'rm -rf "$TMP_ROOT"' EXIT

uv python install "$EXPECTED_PYTHON"

uv venv --python "$EXPECTED_PYTHON" "$TMP_ROOT/venv"

PY="$TMP_ROOT/venv/bin/python"

ACTUAL_PYTHON="$("$PY" -c 'import platform; print(platform.python_version())')"

[ "$ACTUAL_PYTHON" = "$EXPECTED_PYTHON" ] || fail "expected Python $EXPECTED_PYTHON, got $ACTUAL_PYTHON"
pass "Python $EXPECTED_PYTHON"

uv pip sync --python "$PY" --link-mode=copy "$LOCK"

uv pip freeze --python "$PY" | tr '[:upper:]_' '[:lower:]-' | sort > "$TMP_ROOT/installed.txt"

tr '[:upper:]_' '[:lower:]-' < "$LOCK" | sort > "$TMP_ROOT/expected.txt"

if ! diff -u "$TMP_ROOT/expected.txt" "$TMP_ROOT/installed.txt"; then
    fail "installed package set differs from production lock"
fi

pass "exact production package set"

"$PY" -m py_compile \
    src/server.py \
    src/trading212.py \
    src/portfolio_accounting.py \
    src/portfolio_snapshot_service.py

pass "production modules compile"

PYTHONPATH=src "$PY" -c 'import portfolio_accounting, portfolio_snapshot_service'

pass "credential-independent modules import"

printf '\nSTATUS: VERIFIED\n'
printf 'Captured production software/runtime baseline reproduced successfully.\n'
