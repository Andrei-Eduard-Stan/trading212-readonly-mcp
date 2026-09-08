#!/usr/bin/env bash
set -euo pipefail

export LANG="${LANG:-C.UTF-8}"
export LC_ALL="${LC_ALL:-C.UTF-8}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

fail() {
    printf '[FAIL] %s\n' "$1" >&2
    exit 1
}

pass() {
    printf '[PASS] %s\n' "$1"
}

printf 'Trading 212 Read-Only MCP Bootstrap\n'
printf 'Phase: deployment preflight\n\n'

[ "$(id -u)" -eq 0 ] || fail "bootstrap must currently be run as root"

[ -r /etc/os-release ] || fail "/etc/os-release is unavailable"

# shellcheck disable=SC1091
. /etc/os-release

[ "${ID:-}" = "ubuntu" ] || fail "unsupported host: expected Ubuntu, got ${ID:-unknown}"

command -v ansible-playbook >/dev/null 2>&1 || fail "ansible-playbook is not installed yet"

pass "Ubuntu host"
pass "root privileges"
pass "Ansible available"

cd "$ROOT/deploy/ansible"

ansible-playbook site.yml --check --diff

printf '\nSTATUS: PREFLIGHT VERIFIED\n'
printf 'No application, secret, network, or service changes were performed.\n'
