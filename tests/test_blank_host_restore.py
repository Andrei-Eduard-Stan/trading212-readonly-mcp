from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESTORE = ROOT / "scripts" / "restore_from_kit.sh"


def test_restore_requires_offline_kit():
    text = RESTORE.read_text(encoding="utf-8")

    assert "--kit" in text
    assert 'KIT_DIR=""' in text
    assert '[ -n "$KIT_DIR" ]' in text


def test_restore_is_locked_to_certified_host():
    text = RESTORE.read_text(encoding="utf-8")

    assert '[ "${ID:-}" = "ubuntu" ]' in text
    assert '[ "${VERSION_ID:-}" = "26.04" ]' in text


def test_restore_requires_complete_kit_contract():
    text = RESTORE.read_text(encoding="utf-8")

    required = (
        "manifest.sha256",
        "release.txt",
        "repository.bundle",
        "recovery.age",
    )

    for filename in required:
        assert filename in text

    assert '[ ! -L "$KIT_DIR" ]' in text
    assert '[ ! -L "$path" ]' in text
    assert '[ -s "$path" ]' in text


def test_restore_verifies_manifest_before_repository_clone():
    text = RESTORE.read_text(encoding="utf-8")

    manifest = text.index("sha256sum -c manifest.sha256")
    clone = text.index(
        'git clone "$KIT_DIR/repository.bundle" "$REPO_DIR"'
    )

    assert manifest < clone


def test_restore_verifies_git_bundle_and_exact_commit():
    text = RESTORE.read_text(encoding="utf-8")

    clone = text.index(
        'git clone "$KIT_DIR/repository.bundle" "$REPO_DIR"'
    )
    verify = text.index(
        'git -C "$REPO_DIR" bundle verify "$KIT_DIR/repository.bundle"'
    )

    assert clone < verify

    assert '[[ "$EXPECTED_COMMIT" =~ ^[0-9a-f]{40}$ ]]' in text
    assert 'git -C "$REPO_DIR" checkout --detach "$EXPECTED_COMMIT"' in text
    assert 'ACTUAL_COMMIT="$(git -C "$REPO_DIR" rev-parse HEAD)"' in text
    assert '[ "$ACTUAL_COMMIT" = "$EXPECTED_COMMIT" ]' in text


def test_restore_uses_repo_bootstrap_with_encrypted_bundle():
    text = RESTORE.read_text(encoding="utf-8")

    assert '"$REPO_DIR/bootstrap.sh"' in text
    assert "--recovery-bundle" in text
    assert '"$KIT_DIR/recovery.age"' in text


def test_restore_does_not_require_github_credentials_or_network_clone():
    text = RESTORE.read_text(encoding="utf-8")

    forbidden = (
        "github.com",
        "GITHUB_TOKEN",
        "gh auth",
        "ssh-key",
        "deploy key",
        "git@github",
        "https://github",
    )

    for value in forbidden:
        assert value not in text


def test_failed_clone_is_cleaned_up():
    text = RESTORE.read_text(encoding="utf-8")

    assert "trap cleanup_failed_clone EXIT" in text
    assert 'rm -rf -- "$REPO_DIR"' in text
    assert ".restore-complete" in text


def test_bundle_verification_runs_inside_restored_repository():
    text = RESTORE.read_text(encoding="utf-8")

    assert (
        'git -C "$REPO_DIR" bundle verify "$KIT_DIR/repository.bundle"'
        in text
    )

    assert (
        '\ngit bundle verify "$KIT_DIR/repository.bundle"\n'
        not in text
    )


def test_release_file_must_contain_exactly_one_commit_line():
    text = RESTORE.read_text(encoding="utf-8")

    assert 'mapfile -t RELEASE_LINES < "$KIT_DIR/release.txt"' in text
    assert '[ "${#RELEASE_LINES[@]}" -eq 1 ]' in text
    assert 'EXPECTED_COMMIT="${RELEASE_LINES[0]}"' in text
    assert '[[ "$EXPECTED_COMMIT" =~ ^[0-9a-f]{40}$ ]]' in text
