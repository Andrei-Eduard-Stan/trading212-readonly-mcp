#!/usr/bin/env bash
set -euo pipefail

export LANG=C.UTF-8
export LC_ALL=C.UTF-8

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

RECOVERY_BUNDLE=""
OUTPUT_DIR=""

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
  ./scripts/build_dr_kit.sh \
      --recovery-bundle /absolute/path/to/recovery.age \
      --output /absolute/path/to/dr-kit

Options:
  --recovery-bundle PATH
      Existing encrypted Trading 212 recovery bundle.

  --output PATH
      New directory to create as the disaster-recovery kit.

  -h, --help
      Show this help.
USAGE
}

cleanup_failed_build() {
    if [ -n "${OUTPUT_DIR:-}" ] &&
       [ -d "$OUTPUT_DIR" ] &&
       [ ! -f "$OUTPUT_DIR/.build-complete" ]; then
        rm -rf -- "$OUTPUT_DIR"
    fi
}

trap cleanup_failed_build EXIT

while [ "$#" -gt 0 ]; do
    case "$1" in
        --recovery-bundle)
            [ "$#" -ge 2 ] || fail "--recovery-bundle requires a path"
            RECOVERY_BUNDLE="$2"
            shift 2
            ;;
        --output)
            [ "$#" -ge 2 ] || fail "--output requires a path"
            OUTPUT_DIR="$2"
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

[ -n "$RECOVERY_BUNDLE" ] || fail "--recovery-bundle is required"
[ -n "$OUTPUT_DIR" ] || fail "--output is required"

case "$RECOVERY_BUNDLE" in
    /*) ;;
    *) fail "--recovery-bundle must be an absolute path" ;;
esac

case "$OUTPUT_DIR" in
    /*) ;;
    *) fail "--output must be an absolute path" ;;
esac

[ -f "$RECOVERY_BUNDLE" ] || fail "recovery bundle does not exist"
[ ! -L "$RECOVERY_BUNDLE" ] || fail "recovery bundle must not be a symlink"
[ -s "$RECOVERY_BUNDLE" ] || fail "recovery bundle must not be empty"

[ ! -e "$OUTPUT_DIR" ] || fail "output path already exists"
[ -d "$(dirname "$OUTPUT_DIR")" ] || fail "output parent directory does not exist"

case "$OUTPUT_DIR/" in
    "$ROOT/"*)
        fail "DR kit must be created outside the Git repository"
        ;;
esac

command -v git >/dev/null 2>&1 || fail "git is required"
command -v sha256sum >/dev/null 2>&1 || fail "sha256sum is required"

cd "$ROOT"

[ -z "$(git status --porcelain)" ] || \
    fail "repository working tree must be clean"

BRANCH="$(git symbolic-ref --quiet --short HEAD)" || \
    fail "repository must be on a branch, not detached HEAD"

UPSTREAM="$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null)" || \
    fail "current branch has no configured upstream"

LOCAL_COMMIT="$(git rev-parse HEAD)"
UPSTREAM_COMMIT="$(git rev-parse "$UPSTREAM")"

[ "$LOCAL_COMMIT" = "$UPSTREAM_COMMIT" ] || \
    fail "local branch is not synchronized with its upstream"

[[ "$LOCAL_COMMIT" =~ ^[0-9a-f]{40}$ ]] || \
    fail "current release commit is not a full Git SHA-1"

umask 077
mkdir "$OUTPUT_DIR"

printf '%s\n' "$LOCAL_COMMIT" > "$OUTPUT_DIR/release.txt"

git bundle create \
    "$OUTPUT_DIR/repository.bundle" \
    "$BRANCH"

git -C "$ROOT" bundle verify "$OUTPUT_DIR/repository.bundle"

git bundle list-heads "$OUTPUT_DIR/repository.bundle" |
    grep -F "$LOCAL_COMMIT" >/dev/null || \
    fail "release commit is absent from generated Git bundle"

install -m 0755 \
    "$ROOT/scripts/restore_from_kit.sh" \
    "$OUTPUT_DIR/restore_from_kit.sh"

install -m 0600 \
    "$RECOVERY_BUNDLE" \
    "$OUTPUT_DIR/recovery.age"

(
    cd "$OUTPUT_DIR"

    sha256sum \
        restore_from_kit.sh \
        repository.bundle \
        release.txt \
        recovery.age \
        > manifest.sha256

    sha256sum -c manifest.sha256
)

touch "$OUTPUT_DIR/.build-complete"
chmod 0600 "$OUTPUT_DIR/.build-complete"

pass "DR kit created"
printf 'Release: %s\n' "$LOCAL_COMMIT"
printf 'Branch: %s\n' "$BRANCH"
printf 'Output: %s\n' "$OUTPUT_DIR"
