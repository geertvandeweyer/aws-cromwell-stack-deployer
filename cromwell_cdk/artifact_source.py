"""Resolve and verify the Cromwell server JAR before packaging assets."""

from __future__ import annotations

import hashlib
import argparse
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import BinaryIO, Protocol

from cromwell_cdk.config import (
    DEFAULT_CROMWELL_VERSION,
    DeploymentConfig,
    load_config,
    validate_config,
)
from cromwell_cdk.errors import ConfigError, PrereqError


DEFAULT_CROMWELL_URL = (
    "https://github.com/broadinstitute/cromwell/releases/download/92/cromwell-92.jar"
)
DEFAULT_CROMWELL_SHA256 = (
    "e0e3a050d4124e81369a79059e5774142b2f06bd89df4a0b035f559db85cedf5"
)


class _Digest(Protocol):
    """Minimal digest interface accepted by the streaming helper."""

    def update(self, data: bytes, /) -> None:
        """Add bytes to the digest state."""


def stage_cromwell_jar(config: DeploymentConfig, destination: str | Path) -> Path:
    """Stage a pinned Cromwell JAR from the official release or an override.

    The source is copied/downloaded to a temporary sibling file, SHA-256 is
    checked, and only then is it atomically moved into place.

    Args:
        config: Validated deployment settings.
        destination: Target path for the staged JAR.

    Returns:
        Path to the verified JAR.

    Raises:
        ConfigError: If an override is malformed or its configured checksum
            does not match the source.
        PrereqError: If the source cannot be read or downloaded.
    """
    version = str(config.get("cromwell", "version")).strip()
    artifact_url = str(config.get("cromwell", "artifact_url")).strip()
    artifact_path = str(config.get("cromwell", "artifact_path")).strip()
    checksum = str(config.get("cromwell", "sha256")).strip().lower()

    if artifact_url and artifact_path:
        raise ConfigError(
            "Invalid [cromwell] artifact_url/artifact_path: configure only one override"
        )
    if artifact_url or artifact_path:
        expected_sha256 = checksum
        source_url = artifact_url
        source_path = Path(artifact_path).expanduser() if artifact_path else None
    else:
        if version != DEFAULT_CROMWELL_VERSION:
            raise ConfigError(
                "Invalid [cromwell] version: non-default releases require an "
                "artifact_url or artifact_path override with sha256"
            )
        expected_sha256 = DEFAULT_CROMWELL_SHA256
        source_url = DEFAULT_CROMWELL_URL
        source_path = None

    output_path = Path(destination)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    manifest_temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=output_path.parent, prefix=f".{output_path.name}.", delete=False
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            if source_path is not None:
                with source_path.open("rb") as source_file:
                    shutil.copyfileobj(source_file, temporary_file)
            else:
                request = urllib.request.Request(
                    source_url,
                    headers={"User-Agent": "cromwell-cdk-artifact-stager"},
                )
                with urllib.request.urlopen(
                    request, timeout=60, context=_tls_context()
                ) as response:
                    if not response.geturl().lower().startswith("https://"):
                        raise ConfigError(
                            "Invalid [cromwell] artifact_url: HTTPS download "
                            "redirected to a non-HTTPS URL"
                        )
                    shutil.copyfileobj(response, temporary_file)
        actual_sha256 = _sha256(temporary_path)
        if actual_sha256 != expected_sha256:
            raise ConfigError(
                "Invalid [cromwell] sha256: staged artifact checksum mismatch "
                f"(expected {expected_sha256}, got {actual_sha256})"
            )
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output_path.parent,
            prefix=".CHECKSUMS.sha256.",
            delete=False,
        ) as manifest_file:
            manifest_temp_path = Path(manifest_file.name)
            manifest_file.write(f"{actual_sha256}  {output_path.name}\n")
        os.replace(temporary_path, output_path)
        temporary_path = None
        os.replace(manifest_temp_path, output_path.parent / "CHECKSUMS.sha256")
        manifest_temp_path = None
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        source_description = str(source_path) if source_path else source_url
        raise PrereqError(
            f"Unable to stage Cromwell artifact from {source_description}: {exc}"
        ) from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        if manifest_temp_path is not None:
            manifest_temp_path.unlink(missing_ok=True)
    return output_path


def _sha256(path: Path) -> str:
    """Compute SHA-256 incrementally to support large release JARs."""
    digest = hashlib.sha256()
    with path.open("rb") as artifact_file:
        _update_digest(digest, artifact_file)
    return digest.hexdigest()


def _tls_context():
    """Create a TLS context that retains normal CA/hostname validation."""
    import ssl

    return ssl.create_default_context()


def _update_digest(digest: _Digest, artifact_file: BinaryIO) -> None:
    """Feed file blocks into a running digest."""
    for block in iter(lambda: artifact_file.read(1024 * 1024), b""):
        digest.update(block)


def main(argv: list[str] | None = None) -> int:
    """Stage and verify the Cromwell artifact from an INI configuration.

    Args:
        argv: Optional command-line arguments; defaults to process arguments.

    Returns:
        Zero on success or a non-zero status when validation/staging fails.

    Raises:
        None: Expected configuration and prerequisite errors are reported.
    """
    parser = argparse.ArgumentParser(
        description="Stage and SHA-256 verify the configured Cromwell JAR."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configuration.ini"),
        help="Configuration file (default: ./configuration.ini)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("cromwell-assets/cromwell.jar"),
        help="Output JAR path (default: ./cromwell-assets/cromwell.jar)",
    )
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        validate_config(config)
        if not config.get("cromwell", "hosted"):
            raise ConfigError("Invalid [cromwell] hosted: must be true to stage a JAR")
        staged = stage_cromwell_jar(config, args.output)
    except (ConfigError, PrereqError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"Verified Cromwell JAR staged at {staged}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


def entrypoint() -> int:
    """Exit with the staging command's result code."""
    return main()
