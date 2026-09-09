from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "bootstrap.sh"


def test_bootstrap_accepts_encrypted_recovery_bundle():
    text = BOOTSTRAP.read_text(encoding="utf-8")

    assert "--recovery-bundle" in text
    assert 'RECOVERY_BUNDLE=""' in text
    assert 'RECOVERY_DIR=""' in text


def test_bootstrap_materializes_plaintext_only_below_run():
    text = BOOTSTRAP.read_text(encoding="utf-8")

    assert "mktemp -d /run/trading212-recovery.XXXXXX" in text
    assert 'chmod 0700 "$RECOVERY_DIR"' in text
    assert "materialize" in text
    assert '"$RECOVERY_DIR"' in text


def test_bootstrap_guarantees_temporary_recovery_cleanup():
    text = BOOTSTRAP.read_text(encoding="utf-8")

    assert "trap cleanup EXIT" in text
    assert "/run/trading212-recovery.*" in text
    assert 'rm -rf -- "$RECOVERY_DIR"' in text


def test_bootstrap_passes_only_materialized_directory_to_ansible():
    text = BOOTSTRAP.read_text(encoding="utf-8")

    assert (
        '"portfolio_recovery_auth_dir=$RECOVERY_DIR"'
        in text
    )

    ansible_section = text[
        text.index('ANSIBLE_ARGS=(site.yml)') :
    ]

    assert "RECOVERY_BUNDLE" not in ansible_section


def test_bootstrap_performs_real_deployment_not_check_only():
    text = BOOTSTRAP.read_text(encoding="utf-8")

    assert 'ansible-playbook "${ANSIBLE_ARGS[@]}"' in text
    assert "--check" not in text


def test_bootstrap_fails_closed_on_host_and_recovery_dependencies():
    text = BOOTSTRAP.read_text(encoding="utf-8")

    assert '[ "${ID:-}" = "ubuntu" ]' in text
    assert '[ "${VERSION_ID:-}" = "26.04" ]' in text
    assert "command -v ansible-playbook" in text
    assert "command -v python3" in text
    assert "command -v age" in text
