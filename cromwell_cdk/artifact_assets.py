"""Assemble checksum-verified deployment assets for CDK packaging."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil

from cromwell_cdk.artifact_source import stage_cromwell_jar
from cromwell_cdk.config import DeploymentConfig
from cromwell_cdk.errors import ConfigError


ASSET_DIRECTORY = Path(__file__).parent / "assets"
MANIFEST_NAME = "CHECKSUMS.sha256"


def prepare_artifact_assets(config: DeploymentConfig, destination: str | Path) -> Path:
    """Copy reviewed static assets and optionally stage a verified Cromwell JAR.

    The input manifest must account for every static file. Hosted Cromwell is
    staged only when enabled, and the final manifest covers the assembled set.
    """
    source_directory = ASSET_DIRECTORY.resolve()
    manifest_path = source_directory / MANIFEST_NAME
    if not manifest_path.is_file():
        raise ConfigError(f"Missing artifact asset manifest: {manifest_path}")

    entries: dict[str, str] = {}
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            raise ConfigError(f"Malformed artifact asset manifest line: {line!r}")
        digest, filename = parts[0].lower(), parts[1].strip().lstrip("*")
        if (
            len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or not filename
            or Path(filename).name != filename
            or filename == MANIFEST_NAME
            or filename in entries
        ):
            raise ConfigError(f"Invalid artifact asset manifest entry: {line!r}")
        source = source_directory / filename
        if source.is_symlink() or not source.is_file():
            raise ConfigError(f"Manifest asset is missing or unsafe: {filename}")
        actual_digest = _sha256(source)
        if actual_digest != digest:
            raise ConfigError(
                f"Artifact asset checksum mismatch for {filename}: "
                f"expected {digest}, got {actual_digest}"
            )
        entries[filename] = digest

    static_paths = [
        path for path in source_directory.iterdir() if path.name != MANIFEST_NAME
    ]
    unsafe_paths = [path.name for path in static_paths if path.is_symlink()]
    if unsafe_paths:
        raise ConfigError(f"Unsafe symlink in artifact asset directory: {unsafe_paths}")
    static_files = {path.name for path in static_paths if path.is_file()}
    if static_files != set(entries):
        missing_entries = sorted(static_files - set(entries))
        missing_files = sorted(set(entries) - static_files)
        raise ConfigError(
            "Artifact asset manifest does not match the static asset directory "
            f"(unmanifested={missing_entries}, missing={missing_files})"
        )

    output_directory = Path(destination)
    output_directory.mkdir(parents=True, exist_ok=True)
    if any(output_directory.iterdir()):
        raise ConfigError(
            f"Artifact asset destination must be empty: {output_directory}"
        )
    for filename in sorted(entries):
        shutil.copy2(source_directory / filename, output_directory / filename)

    if config.get("cromwell", "hosted"):
        if "cromwell.jar" in entries:
            raise ConfigError(
                "Artifact asset directory reserves cromwell.jar for the verified "
                "hosted Cromwell release"
            )
        jar_path = output_directory / "cromwell.jar"
        stage_cromwell_jar(config, jar_path)
        entries[jar_path.name] = _sha256(jar_path)

    manifest_output = output_directory / MANIFEST_NAME
    with manifest_output.open("w", encoding="utf-8", newline="\n") as manifest:
        for filename, digest in sorted(entries.items()):
            manifest.write(f"{digest}  {filename}\n")
    os.chmod(manifest_output, 0o644)
    return output_directory


def _sha256(path: Path) -> str:
    """Compute SHA-256 incrementally for large assets."""
    digest = hashlib.sha256()
    with path.open("rb") as asset:
        for block in iter(lambda: asset.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
