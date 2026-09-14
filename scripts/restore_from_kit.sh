#!/usr/bin/env bash
set -euo pipefail

export LANG=C.UTF-8
export LC_ALL=C.UTF-8

KIT_DIR=""
RESTORE_ROOT="/opt/trading212-readonly-mcp-recovery"
REPO_DIR="$RESTORE_ROOT/repository"

fail() {
    printf '[FAIL] %s\n' "$1" >&2
    exit 1
}

pass() {
    printf '[PASS] %s\n' "$1"
}

usage() {
    cat <<'USAGE'
Usage:
  sudo ./restore_from_kit.sh --kit /absolute/path/to/dr-kit

Options:
  --kit PATH
      Path to an offline Trading 212 MCP disaster-recovery kit.

  -h, --help
      Show this help.
USAGE
}

cleanup_failed_clone() {
    if [ -n "${REPO_DIR:-}" ] &&
       [ -d "$REPO_DIR" ] &&
       [ ! -f "$REPO_DIR/.restore-complete" ]; then
        rm -rf -- "$REPO_DIR"
    fi
}

trap cleanup_failed_clone EXIT

while [ "$#" -gt 0 ]; do
    case "$1" in
        --kit)
            [ "$#" -ge 2 ] || fail "--kit requires a path"
            KIT_DIR="$2"
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

[ -n "$KIT_DIR" ] || fail "--kit is required"
[ "$(id -u)" -eq 0 ] || fail "restore must be run as root"
[ -r /etc/os-release ] || fail "/etc/os-release is unavailable"

# shellcheck disable=SC1091
. /etc/os-release

[ "${ID:-}" = "ubuntu" ] || \
    fail "unsupported host: expected Ubuntu, got ${ID:-unknown}"

[ "${VERSION_ID:-}" = "26.04" ] || \
    fail "unsupported Ubuntu release: expected 26.04, got ${VERSION_ID:-unknown}"

case "$KIT_DIR" in
    /*) ;;
    *) fail "--kit must be an absolute path" ;;
esac

[ -d "$KIT_DIR" ] || fail "DR kit directory does not exist"
[ ! -L "$KIT_DIR" ] || fail "DR kit directory must not be a symlink"

REQUIRED_FILES=(
    manifest.sha256
    release.txt
    repository.bundle
    recovery.age
)

for file in "${REQUIRED_FILES[@]}"; do
    path="$KIT_DIR/$file"

    [ -f "$path" ] || fail "required DR kit file missing: $file"
    [ ! -L "$path" ] || fail "DR kit file must not be a symlink: $file"
    [ -s "$path" ] || fail "DR kit file is empty: $file"
done

printf '[INFO] Installing minimal restore prerequisites.\n'

apt-get update

DEBIAN_FRONTEND=noninteractive apt-get install -y \
    --no-install-recommends \
    ca-certificates \
    git

command -v git >/dev/null 2>&1 || \
    fail "git is unavailable after installation"

command -v sha256sum >/dev/null 2>&1 || \
    fail "sha256sum is unavailable"

printf '[INFO] Verifying DR kit manifest.\n'

(
    cd "$KIT_DIR"
    sha256sum -c manifest.sha256
)

pass "DR kit manifest"

mapfile -t RELEASE_LINES < "$KIT_DIR/release.txt"

[ "${#RELEASE_LINES[@]}" -eq 1 ] || \
    fail "release.txt must contain exactly one line"

EXPECTED_COMMIT="${RELEASE_LINES[0]}"

[[ "$EXPECTED_COMMIT" =~ ^[0-9a-f]{40}$ ]] || \
    fail "release.txt must contain exactly one full 40-character lowercase Git commit"

mkdir -p "$RESTORE_ROOT"

[ ! -e "$REPO_DIR" ] || \
    fail "restore repository destination already exists"

git clone "$KIT_DIR/repository.bundle" "$REPO_DIR"

git -C "$REPO_DIR" bundle verify "$KIT_DIR/repository.bundle"

pass "Git bundle"

git -C "$REPO_DIR" cat-file -e "${EXPECTED_COMMIT}^{commit}" || \
    fail "recorded release commit is absent from repository bundle"

git -C "$REPO_DIR" checkout --detach "$EXPECTED_COMMIT"

ACTUAL_COMMIT="$(git -C "$REPO_DIR" rev-parse HEAD)"

[ "$ACTUAL_COMMIT" = "$EXPECTED_COMMIT" ] || \
    fail "restored repository commit does not match release.txt"

pass "Exact repository commit $ACTUAL_COMMIT"

[ -x "$REPO_DIR/bootstrap.sh" ] || \
    fail "restored bootstrap.sh is missing or not executable"

"$REPO_DIR/bootstrap.sh" \
    --recovery-bundle \
    "$KIT_DIR/recovery.age"

touch "$REPO_DIR/.restore-complete"
chmod 0600 "$REPO_DIR/.restore-complete"

printf '\nSTATUS: DISASTER RECOVERY COMPLETED\n'
