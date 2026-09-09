#!/usr/bin/env bash
set -euo pipefail

export LANG=C.UTF-8
export LC_ALL=C.UTF-8

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RECOVERY_BUNDLE=""
RECOVERY_DIR=""

fail() {
    printf '[FAIL] %s\n' "$1" >&2
    exit 1
}

pass() {
    printf '[PASS] %s\n' "$1"
}

ensure_universe_repository() {
    if apt-cache show ansible-core >/dev/null 2>&1; then
        return
    fi

    printf '[INFO] Enabling Ubuntu universe repository.\n'

    DEBIAN_FRONTEND=noninteractive apt-get install -y         --no-install-recommends         software-properties-common

    add-apt-repository -y universe
    apt-get update

    apt-cache show ansible-core >/dev/null 2>&1 ||         fail "ansible-core remains unavailable after enabling universe"
}

ensure_bootstrap_tooling() {
    command -v apt-get >/dev/null 2>&1 ||         fail "apt-get is required on the supported Ubuntu host"

    command -v apt-cache >/dev/null 2>&1 ||         fail "apt-cache is required on the supported Ubuntu host"

    printf '[INFO] Refreshing Ubuntu package metadata.\n'
    apt-get update

    ensure_universe_repository

    BOOTSTRAP_PACKAGES=(
        ca-certificates
        python3
        python3-apt
        ansible-core
    )

    if [ -n "$RECOVERY_BUNDLE" ]; then
        BOOTSTRAP_PACKAGES+=(age)
    fi

    printf '[INFO] Ensuring bootstrap dependencies are installed.\n'

    DEBIAN_FRONTEND=noninteractive apt-get install -y         --no-install-recommends         "${BOOTSTRAP_PACKAGES[@]}"

    command -v ansible-playbook >/dev/null 2>&1 ||         fail "ansible-playbook is unavailable after bootstrap installation"

    command -v python3 >/dev/null 2>&1 ||         fail "python3 is unavailable after bootstrap installation"

    if [ -n "$RECOVERY_BUNDLE" ]; then
        command -v age >/dev/null 2>&1 ||             fail "age is unavailable after bootstrap installation"
    fi
}

usage() {
    cat <<'USAGE'
Usage:
  sudo ./bootstrap.sh
  sudo ./bootstrap.sh --recovery-bundle /absolute/path/to/recovery.age

Options:
  --recovery-bundle PATH
      Unlock an encrypted Trading 212 recovery bundle and use it only for
      this deployment run.

  -h, --help
      Show this help.
USAGE
}

cleanup() {
    if [ -n "${RECOVERY_DIR:-}" ] && [ -d "$RECOVERY_DIR" ]; then
        case "$RECOVERY_DIR" in
            /run/trading212-recovery.*)
                rm -rf -- "$RECOVERY_DIR"
                ;;
            *)
                printf '[WARN] Refusing cleanup outside expected /run path: %s\n' \
                    "$RECOVERY_DIR" >&2
                ;;
        esac
    fi
}

trap cleanup EXIT

while [ "$#" -gt 0 ]; do
    case "$1" in
        --recovery-bundle)
            [ "$#" -ge 2 ] || fail "--recovery-bundle requires a path"
            RECOVERY_BUNDLE="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            fail "unknown argument: $1"
            ;;
    esac
done

printf 'Trading 212 Read-Only MCP Bootstrap\n'
printf 'Mode: deployment\n\n'

[ "$(id -u)" -eq 0 ] || fail "bootstrap must be run as root"

[ -r /etc/os-release ] || fail "/etc/os-release is unavailable"

# shellcheck disable=SC1091
. /etc/os-release

[ "${ID:-}" = "ubuntu" ] || \
    fail "unsupported host: expected Ubuntu, got ${ID:-unknown}"

[ "${VERSION_ID:-}" = "26.04" ] || \
    fail "unsupported Ubuntu release: expected 26.04, got ${VERSION_ID:-unknown}"

pass "Ubuntu 26.04 host"
pass "root privileges"

ensure_bootstrap_tooling
pass "Bootstrap tooling available"

if [ -n "$RECOVERY_BUNDLE" ]; then
    RECOVERY_DIR="$(mktemp -d /run/trading212-recovery.XXXXXX)"
    chmod 0700 "$RECOVERY_DIR"

    python3 "$ROOT/scripts/recovery_bundle.py" \
        materialize \
        "$RECOVERY_BUNDLE" \
        "$RECOVERY_DIR"

    pass "Encrypted recovery bundle materialized in temporary /run storage"
fi

cd "$ROOT/deploy/ansible"

ANSIBLE_ARGS=(site.yml)

if [ -n "$RECOVERY_DIR" ]; then
    ANSIBLE_ARGS+=(
        --extra-vars
        "portfolio_recovery_auth_dir=$RECOVERY_DIR"
    )
fi

ansible-playbook "${ANSIBLE_ARGS[@]}"

printf '\nSTATUS: DEPLOYMENT COMPLETED\n'

if [ -n "$RECOVERY_DIR" ]; then
    printf 'Temporary recovery material will now be removed from /run.\n'
fi
