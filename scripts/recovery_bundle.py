#!/usr/bin/env python3

from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any


SCHEMA = "trading212-readonly-mcp.recovery.v1"

PAYLOAD_FIELDS = {
    "schema",
    "trading212_api_key",
    "trading212_api_secret",
}

MATERIALIZED_FILES = {
    "trading212_api_key": "trading212_api_key",
    "trading212_api_secret": "trading212_api_secret",
}


def require_age() -> str:
    age = shutil.which("age")
    if age is None:
        raise RuntimeError(
            "age is required but was not found in PATH."
        )
    return age


def validate_auth_value(name: str, value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string.")

    if not value:
        raise ValueError(f"{name} must not be empty.")

    if value != value.strip():
        raise ValueError(
            f"{name} must not contain leading or trailing whitespace."
        )

    if any(character in value for character in ("\x00", "\n", "\r")):
        raise ValueError(
            f"{name} contains forbidden control characters."
        )

    return value


def validate_payload(payload: Any) -> dict[str, str]:
    if not isinstance(payload, dict):
        raise ValueError("Recovery payload must be a JSON object.")

    if set(payload) != PAYLOAD_FIELDS:
        raise ValueError(
            "Recovery payload does not match the required schema."
        )

    if payload["schema"] != SCHEMA:
        raise ValueError(
            f"Unsupported recovery schema: {payload['schema']!r}."
        )

    return {
        "trading212_api_key": validate_auth_value(
            "trading212_api_key",
            payload["trading212_api_key"],
        ),
        "trading212_api_secret": validate_auth_value(
            "trading212_api_secret",
            payload["trading212_api_secret"],
        ),
    }


def validate_bundle_path(bundle: Path) -> None:
    try:
        info = bundle.lstat()
    except FileNotFoundError as exc:
        raise ValueError("Recovery bundle does not exist.") from exc

    if stat.S_ISLNK(info.st_mode):
        raise ValueError("Recovery bundle must not be a symlink.")

    if not stat.S_ISREG(info.st_mode):
        raise ValueError("Recovery bundle must be a regular file.")

    if info.st_size <= 0:
        raise ValueError("Recovery bundle must not be empty.")


def prepare_output_directory(output_dir: Path) -> None:
    if not output_dir.is_absolute():
        raise ValueError(
            "Materialization directory must be an absolute path."
        )

    run_root = Path("/run").resolve()
    resolved = output_dir.resolve(strict=False)

    if run_root not in resolved.parents:
        raise ValueError(
            "Materialized broker auth may only be written below /run."
        )

    if output_dir.is_symlink():
        raise ValueError(
            "Materialization directory must not be a symlink."
        )

    if output_dir.exists():
        if not output_dir.is_dir():
            raise ValueError(
                "Materialization destination is not a directory."
            )

        if any(output_dir.iterdir()):
            raise ValueError(
                "Materialization directory must be empty."
            )
    else:
        output_dir.mkdir(mode=0o700)

    os.chmod(output_dir, 0o700)


def write_materialized_file(path: Path, value: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL

    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW

    fd = os.open(path, flags, 0o600)

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(value)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise

    os.chmod(path, 0o600)


def create_bundle(output: Path) -> None:
    age = require_age()

    if output.exists() or output.is_symlink():
        raise ValueError(
            "Refusing to overwrite an existing recovery bundle."
        )

    if not output.parent.exists():
        raise ValueError(
            "Recovery bundle parent directory does not exist."
        )

    api_key = validate_auth_value(
        "trading212_api_key",
        getpass.getpass("Trading 212 API key: "),
    )

    api_secret = validate_auth_value(
        "trading212_api_secret",
        getpass.getpass("Trading 212 API secret: "),
    )

    payload = {
        "schema": SCHEMA,
        "trading212_api_key": api_key,
        "trading212_api_secret": api_secret,
    }

    encoded = json.dumps(
        payload,
        separators=(",", ":"),
    ).encode("utf-8")

    try:
        subprocess.run(
            [
                age,
                "-p",
                "-o",
                str(output),
            ],
            input=encoded,
            check=True,
        )
    except Exception:
        output.unlink(missing_ok=True)
        raise

    validate_bundle_path(output)
    os.chmod(output, 0o600)

    print(f"Encrypted recovery bundle created: {output}")


def materialize_bundle(bundle: Path, output_dir: Path) -> None:
    age = require_age()

    validate_bundle_path(bundle)
    prepare_output_directory(output_dir)

    created: list[Path] = []

    try:
        result = subprocess.run(
            [
                age,
                "-d",
                str(bundle),
            ],
            check=True,
            stdout=subprocess.PIPE,
        )

        payload = json.loads(result.stdout.decode("utf-8"))
        values = validate_payload(payload)

        for field, filename in MATERIALIZED_FILES.items():
            target = output_dir / filename
            write_materialized_file(target, values[field])
            created.append(target)

    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        raise

    print(f"Broker auth materialized under: {output_dir}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create or materialize an encrypted Trading 212 "
            "disaster-recovery bundle."
        )
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    create = subparsers.add_parser(
        "create",
        help="Create an encrypted recovery bundle.",
    )
    create.add_argument("output", type=Path)

    materialize = subparsers.add_parser(
        "materialize",
        help="Decrypt a recovery bundle into protected /run storage.",
    )
    materialize.add_argument("bundle", type=Path)
    materialize.add_argument("output_dir", type=Path)

    return parser


def main() -> int:
    args = build_parser().parse_args()

    try:
        if args.command == "create":
            create_bundle(args.output)
        elif args.command == "materialize":
            materialize_bundle(
                args.bundle,
                args.output_dir,
            )
        else:
            raise RuntimeError("Unsupported command.")

    except (
        ValueError,
        RuntimeError,
        OSError,
        subprocess.CalledProcessError,
        json.JSONDecodeError,
    ) as exc:
        print(
            f"[FAIL] {exc}",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create or materialize an encrypted Trading 212 "
            "disaster-recovery bundle."
        )
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    create = subparsers.add_parser(
        "create",
        help="Create an encrypted recovery bundle.",
    )
    create.add_argument("output", type=Path)

    materialize = subparsers.add_parser(
        "materialize",
        help="Decrypt a recovery bundle into protected /run storage.",
    )
    materialize.add_argument("bundle", type=Path)
    materialize.add_argument("output_dir", type=Path)

    return parser


def main() -> int:
    args = build_parser().parse_args()

    try:
        if args.command == "create":
            create_bundle(args.output)
        elif args.command == "materialize":
            materialize_bundle(
                args.bundle,
                args.output_dir,
            )
        else:
            raise RuntimeError("Unsupported command.")

    except (
        ValueError,
        RuntimeError,
        OSError,
        subprocess.CalledProcessError,
        json.JSONDecodeError,
    ) as exc:
        print(
            f"[FAIL] {exc}",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
