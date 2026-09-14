from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "scripts" / "build_dr_kit.sh"


def test_builder_requires_external_encrypted_recovery_bundle():
    text = BUILDER.read_text(encoding="utf-8")

    assert "--recovery-bundle" in text
    assert '[ -f "$RECOVERY_BUNDLE" ]' in text
    assert '[ ! -L "$RECOVERY_BUNDLE" ]' in text
    assert '[ -s "$RECOVERY_BUNDLE" ]' in text


def test_builder_requires_new_output_outside_repository():
    text = BUILDER.read_text(encoding="utf-8")

    assert "--output" in text
    assert '[ ! -e "$OUTPUT_DIR" ]' in text
    assert 'fail "DR kit must be created outside the Git repository"' in text


def test_builder_requires_clean_repository():
    text = BUILDER.read_text(encoding="utf-8")

    assert "git status --porcelain" in text
    assert 'fail "repository working tree must be clean"' in text


def test_builder_requires_branch_synced_with_upstream():
    text = BUILDER.read_text(encoding="utf-8")

    assert "git symbolic-ref --quiet --short HEAD" in text
    assert "'@{u}'" in text
    assert 'LOCAL_COMMIT="$(git rev-parse HEAD)"' in text
    assert 'UPSTREAM_COMMIT="$(git rev-parse "$UPSTREAM")"' in text
    assert '[ "$LOCAL_COMMIT" = "$UPSTREAM_COMMIT" ]' in text


def test_builder_creates_and_verifies_git_bundle():
    text = BUILDER.read_text(encoding="utf-8")

    assert "git bundle create" in text
    assert 'git -C "$ROOT" bundle verify "$OUTPUT_DIR/repository.bundle"' in text
    assert 'git bundle list-heads "$OUTPUT_DIR/repository.bundle"' in text


def test_builder_records_exact_release_commit():
    text = BUILDER.read_text(encoding="utf-8")

    assert "[[ \"$LOCAL_COMMIT\" =~ ^[0-9a-f]{40}$ ]]" in text
    assert 'printf \'%s\\n\' "$LOCAL_COMMIT" > "$OUTPUT_DIR/release.txt"' in text


def test_builder_copies_only_encrypted_recovery_material():
    text = BUILDER.read_text(encoding="utf-8")

    assert '"$RECOVERY_BUNDLE"' in text
    assert '"$OUTPUT_DIR/recovery.age"' in text

    forbidden = (
        "trading212_api_key",
        "trading212_api_secret",
        "getpass",
    )

    for value in forbidden:
        assert value not in text


def test_builder_generates_and_verifies_manifest():
    text = BUILDER.read_text(encoding="utf-8")

    assert "restore_from_kit.sh" in text
    assert "repository.bundle" in text
    assert "release.txt" in text
    assert "recovery.age" in text
    assert "> manifest.sha256" in text
    assert "sha256sum -c manifest.sha256" in text


def test_failed_build_is_removed():
    text = BUILDER.read_text(encoding="utf-8")

    assert "trap cleanup_failed_build EXIT" in text
    assert 'rm -rf -- "$OUTPUT_DIR"' in text
    assert ".build-complete" in text
