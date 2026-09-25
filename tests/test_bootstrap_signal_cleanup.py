from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "bootstrap.sh"


def test_bootstrap_cleans_recovery_material_on_exit_and_signals():
    text = BOOTSTRAP.read_text(encoding="utf-8")

    assert "trap cleanup EXIT" in text
    assert "trap 'exit 129' HUP" in text
    assert "trap 'exit 130' INT" in text
    assert "trap 'exit 143' TERM" in text

    assert "/run/trading212-recovery.*" in text
    assert 'rm -rf -- "$RECOVERY_DIR"' in text


def test_recovery_directory_is_recorded_before_materialization():
    text = BOOTSTRAP.read_text(encoding="utf-8")

    created = text.index(
        'RECOVERY_DIR="$(mktemp -d /run/trading212-recovery.XXXXXX)"'
    )
    materialized = text.index(
        'materialize \\\n'
        '        "$RECOVERY_BUNDLE" \\\n'
        '        "$RECOVERY_DIR"'
    )

    assert created < materialized
