import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "recovery_bundle.py"

spec = importlib.util.spec_from_file_location(
    "recovery_bundle",
    SCRIPT,
)
assert spec is not None
assert spec.loader is not None

recovery_bundle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery_bundle)


def test_recovery_payload_schema_is_exact():
    payload = {
        "schema": recovery_bundle.SCHEMA,
        "trading212_api_key": "example-api-key",
        "trading212_api_secret": "example-api-token",
    }

    result = recovery_bundle.validate_payload(payload)

    assert result["trading212_api_key"] == "example-api-key"
    assert result["trading212_api_secret"] == "example-api-token"


def test_recovery_payload_rejects_missing_or_extra_fields():
    missing = {
        "schema": recovery_bundle.SCHEMA,
        "trading212_api_key": "example-api-key",
    }

    extra = {
        "schema": recovery_bundle.SCHEMA,
        "trading212_api_key": "example-api-key",
        "trading212_api_secret": "example-api-token",
        "unexpected": "value",
    }

    with pytest.raises(ValueError):
        recovery_bundle.validate_payload(missing)

    with pytest.raises(ValueError):
        recovery_bundle.validate_payload(extra)


def test_recovery_values_fail_closed_on_invalid_input():
    invalid = (
        "",
        " leading-space",
        "trailing-space ",
        "line\nbreak",
        "line\rbreak",
        "nul\x00byte",
    )

    for value in invalid:
        with pytest.raises(ValueError):
            recovery_bundle.validate_auth_value(
                "test-field",
                value,
            )


def test_bundle_creation_uses_hidden_input_and_passphrase_encryption():
    text = SCRIPT.read_text(encoding="utf-8")

    assert "getpass.getpass" in text
    assert '"-p"' in text
    assert "shell=True" not in text
    assert "os.chmod(output, 0o600)" in text
    assert "Refusing to overwrite" in text


def test_materialization_decrypts_to_memory_and_restricts_plaintext_to_run():
    text = SCRIPT.read_text(encoding="utf-8")

    assert '"-d"' in text
    assert "stdout=subprocess.PIPE" in text
    assert 'Path("/run")' in text
    assert "Materialized broker auth may only be written below /run." in text


def test_materialized_files_use_exclusive_restricted_creation():
    text = SCRIPT.read_text(encoding="utf-8")

    assert "os.O_EXCL" in text
    assert 'hasattr(os, "O_NOFOLLOW")' in text
    assert "os.open(path, flags, 0o600)" in text
    assert "os.chmod(path, 0o600)" in text


def test_recovery_bundle_exposes_create_and_materialize_cli():
    text = SCRIPT.read_text(encoding="utf-8")

    assert "def build_parser()" in text
    assert 'subparsers.add_parser(' in text
    assert '"create"' in text
    assert '"materialize"' in text
    assert 'if __name__ == "__main__":' in text
    assert "raise SystemExit(main())" in text




def test_recovery_bundle_parser_accepts_both_supported_commands():
    parser = recovery_bundle.build_parser()

    create = parser.parse_args(
        ["create", "/tmp/example-recovery.age"]
    )
    assert create.command == "create"
    assert create.output == Path("/tmp/example-recovery.age")

    materialize = parser.parse_args(
        [
            "materialize",
            "/tmp/example-recovery.age",
            "/run/example-recovery",
        ]
    )
    assert materialize.command == "materialize"
    assert materialize.bundle == Path("/tmp/example-recovery.age")
    assert materialize.output_dir == Path("/run/example-recovery")
