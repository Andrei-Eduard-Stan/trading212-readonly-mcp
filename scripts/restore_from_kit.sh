#!/usr/bin/env bash
set -euo pipefail

export LANG=C.UTF-8
export LC_ALL=C.UTF-8

KIT_DIR=""

PUBLIC_HOST_OVERRIDE=""
RESOURCE_URL_OVERRIDE=""
TAILSCALE_HOSTNAME_OVERRIDE=""

RESTORE_ROOT="/opt/trading212-readonly-mcp-recovery"
REPO_DIR="$RESTORE_ROOT/repository"
RESTORE_MARKER="$RESTORE_ROOT/.restore-complete"

REPO_CREATED_THIS_RUN=0
REPO_VALIDATED=0

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

  --public-host HOST
      Override the public Funnel/MCP hostname for this restore.

  --tailscale-hostname HOST
      Override the expected short Tailscale node hostname.

  --resource-url URL
      Override the OAuth/MCP resource URL independently.

  -h, --help
      Show this help.
USAGE
}

cleanup_unvalidated_clone() {
    if [ "${REPO_CREATED_THIS_RUN:-0}" -eq 1 ] &&
       [ "${REPO_VALIDATED:-0}" -eq 0 ] &&
       { [ -e "${REPO_DIR:-}" ] || [ -L "${REPO_DIR:-}" ]; }; then
        rm -rf -- "$REPO_DIR"
    fi
}

trap cleanup_unvalidated_clone EXIT

while [ "$#" -gt 0 ]; do
    case "$1" in
        --kit)
            [ "$#" -ge 2 ] || fail "--kit requires a path"
            KIT_DIR="$2"
            shift 2
            ;;
        --public-host)
            [ "$#" -ge 2 ] || fail "--public-host requires a value"
            PUBLIC_HOST_OVERRIDE="$2"
            shift 2
            ;;
        --tailscale-hostname)
            [ "$#" -ge 2 ] || fail "--tailscale-hostname requires a value"
            TAILSCALE_HOSTNAME_OVERRIDE="$2"
            shift 2
            ;;
        --resource-url)
            [ "$#" -ge 2 ] || fail "--resource-url requires a value"
            RESOURCE_URL_OVERRIDE="$2"
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

if [ -e "$RESTORE_ROOT" ] || [ -L "$RESTORE_ROOT" ]; then
    [ -d "$RESTORE_ROOT" ] && [ ! -L "$RESTORE_ROOT" ] || \
        fail "restore root exists but is not a real directory"
else
    mkdir -p "$RESTORE_ROOT"
fi

if [ -e "$REPO_DIR" ] || [ -L "$REPO_DIR" ]; then
    [ -d "$REPO_DIR" ] && [ ! -L "$REPO_DIR" ] || \
        fail "restore repository destination is not a real directory"

    printf '[INFO] Reusing existing reconstructed repository.\n'
else
    REPO_CREATED_THIS_RUN=1
    git clone "$KIT_DIR/repository.bundle" "$REPO_DIR"
fi

git -C "$REPO_DIR" bundle verify "$KIT_DIR/repository.bundle"

pass "Git bundle"

git -C "$REPO_DIR" cat-file -e "${EXPECTED_COMMIT}^{commit}" || \
    fail "recorded release commit is absent from repository bundle"

if [ "$REPO_CREATED_THIS_RUN" -eq 1 ]; then
    git -C "$REPO_DIR" checkout --detach "$EXPECTED_COMMIT"
fi

ACTUAL_COMMIT="$(git -C "$REPO_DIR" rev-parse HEAD)"

[ "$ACTUAL_COMMIT" = "$EXPECTED_COMMIT" ] || \
    fail "restored repository commit does not match release.txt"

RESTORE_DIRTY="$(
    git -C "$REPO_DIR" status --porcelain --untracked-files=all
)"

[ -z "$RESTORE_DIRTY" ] || \
    fail "restored repository is not clean"

REPO_VALIDATED=1

pass "Exact clean repository commit $ACTUAL_COMMIT"

[ -x "$REPO_DIR/bootstrap.sh" ] || \
    fail "restored bootstrap.sh is missing or not executable"

BOOTSTRAP_ARGS=(
    --recovery-bundle
    "$KIT_DIR/recovery.age"
)

if [ -n "$PUBLIC_HOST_OVERRIDE" ]; then
    BOOTSTRAP_ARGS+=(
        --public-host
        "$PUBLIC_HOST_OVERRIDE"
    )
fi

if [ -n "$TAILSCALE_HOSTNAME_OVERRIDE" ]; then
    BOOTSTRAP_ARGS+=(
        --tailscale-hostname
        "$TAILSCALE_HOSTNAME_OVERRIDE"
    )
fi

if [ -n "$RESOURCE_URL_OVERRIDE" ]; then
    BOOTSTRAP_ARGS+=(
        --resource-url
        "$RESOURCE_URL_OVERRIDE"
    )
fi

[ ! -L "$RESTORE_MARKER" ] || \
    fail "restore completion marker must not be a symlink"

rm -f -- "$RESTORE_MARKER"

"$REPO_DIR/bootstrap.sh" "${BOOTSTRAP_ARGS[@]}"

touch "$RESTORE_MARKER"
chmod 0600 "$RESTORE_MARKER"

printf '\nSTATUS: DISASTER RECOVERY COMPLETED\n'
