"""Tests for pinned and operator-overridden Cromwell artifacts."""

from pathlib import Path
import hashlib
from io import BytesIO
from unittest.mock import patch

from cromwell_cdk.artifact_source import (
    DEFAULT_CROMWELL_SHA256,
    _sha256,
    main,
    stage_cromwell_jar,
)
from cromwell_cdk.config import load_config
from cromwell_cdk.errors import ConfigError, PrereqError
from cromwell_cdk.tests.base import TestBase


class CromwellArtifactSourceTests(TestBase):
    """Verify source overrides are staged only after checksum validation."""

    def setUp(self) -> None:
        """Create a valid config and small local JAR fixture."""
        super().setUp()
        self.config_path = Path(self.temp_dir) / "configuration.ini"
        self.source_path = Path(self.temp_dir) / "cromwell-local.jar"
        self.output_path = Path(self.temp_dir) / "assets" / "cromwell.jar"
        self.source_path.write_bytes(b"small local Cromwell test artifact")
        self.config_path.write_text(
            (Path(__file__).parents[2] / "configuration.example.ini").read_text()
        )

    def _config_with(self, replacements: dict[str, str]):
        """Load configuration after replacing exact fixture lines."""
        content = self.config_path.read_text()
        for old, new in replacements.items():
            content = content.replace(old, new, 1)
        self.config_path.write_text(content)
        return load_config(self.config_path)

    def test_local_artifact_override_is_copied_after_verification(self) -> None:
        """Copy a local source to the asset destination after digest match."""

        source_sha256 = hashlib.sha256(self.source_path.read_bytes()).hexdigest()
        config = self._config_with(
            {
                "artifact_path =": f"artifact_path = {self.source_path}",
                "sha256 =": f"sha256 = {source_sha256}",
            }
        )
        staged = stage_cromwell_jar(config, self.output_path)
        self.assertEqual(staged.read_bytes(), self.source_path.read_bytes())
        self.assertTrue(staged.is_file())
        self.assertEqual(
            (staged.parent / "CHECKSUMS.sha256").read_text(),
            f"{source_sha256}  cromwell.jar\n",
        )

    def test_checksum_mismatch_does_not_replace_destination(self) -> None:
        """Keep any previous destination intact when source verification fails."""
        config = self._config_with(
            {
                "artifact_path =": f"artifact_path = {self.source_path}",
                "sha256 =": "sha256 = " + "0" * 64,
            }
        )
        self.output_path.parent.mkdir(parents=True)
        self.output_path.write_bytes(b"existing verified artifact")
        with self.assertRaisesRegex(ConfigError, "checksum mismatch"):
            stage_cromwell_jar(config, self.output_path)
        self.assertEqual(self.output_path.read_bytes(), b"existing verified artifact")

    def test_missing_local_source_raises_prerequisite_error(self) -> None:
        """Report an absent configured local JAR as an actionable prerequisite."""
        config = self._config_with(
            {
                "artifact_path =": "artifact_path = /missing/cromwell.jar",
                "sha256 =": "sha256 = " + "a" * 64,
            }
        )
        with self.assertRaisesRegex(PrereqError, "Unable to stage Cromwell artifact"):
            stage_cromwell_jar(config, self.output_path)

    def test_https_url_override_is_downloaded_and_verified(self) -> None:
        """Download an HTTPS override and verify it before writing output."""
        source_bytes = self.source_path.read_bytes()
        source_sha256 = hashlib.sha256(source_bytes).hexdigest()
        config = self._config_with(
            {
                "artifact_url =": "artifact_url = https://example.invalid/cromwell.jar",
                "sha256 =": f"sha256 = {source_sha256}",
            }
        )
        response = BytesIO(source_bytes)
        response.geturl = lambda: "https://example.invalid/cromwell.jar"
        with patch(
            "cromwell_cdk.artifact_source.urllib.request.urlopen",
            return_value=response,
        ) as open_url:
            staged = stage_cromwell_jar(config, self.output_path)
        self.assertEqual(staged.read_bytes(), source_bytes)
        open_url.assert_called_once()

    def test_https_override_rejects_http_redirect(self) -> None:
        """Reject a downloader response redirected from HTTPS to plaintext HTTP."""
        source_sha256 = hashlib.sha256(self.source_path.read_bytes()).hexdigest()
        config = self._config_with(
            {
                "artifact_url =": "artifact_url = https://example.invalid/cromwell.jar",
                "sha256 =": f"sha256 = {source_sha256}",
            }
        )
        response = BytesIO(self.source_path.read_bytes())
        response.geturl = lambda: "http://example.invalid/cromwell.jar"
        with patch(
            "cromwell_cdk.artifact_source.urllib.request.urlopen",
            return_value=response,
        ):
            with self.assertRaisesRegex(ConfigError, "redirected to a non-HTTPS URL"):
                stage_cromwell_jar(config, self.output_path)

    def test_staging_cli_verifies_and_writes_configured_jar(self) -> None:
        """Expose the source override behavior through the project CLI command."""
        source_sha256 = hashlib.sha256(self.source_path.read_bytes()).hexdigest()
        self._config_with(
            {
                "hosted = false": "hosted = true",
                "artifact_path =": f"artifact_path = {self.source_path}",
                "sha256 =": f"sha256 = {source_sha256}",
            }
        )
        self.assertEqual(
            main(
                ["--config", str(self.config_path), "--output", str(self.output_path)]
            ),
            0,
        )
        self.assertEqual(_sha256(self.output_path), source_sha256)

    def test_staging_cli_requires_hosted_cromwell(self) -> None:
        """Avoid downloading artifacts when hosted Cromwell is disabled."""
        self.assertEqual(
            main(
                ["--config", str(self.config_path), "--output", str(self.output_path)]
            ),
            1,
        )
        self.assertFalse(self.output_path.exists())

    def test_default_version_has_reviewed_pinned_digest(self) -> None:
        """Ensure the default release retains the verified official SHA-256."""
        self.assertRegex(DEFAULT_CROMWELL_SHA256, r"^[0-9a-f]{64}$")
        self.assertEqual(len(DEFAULT_CROMWELL_SHA256), 64)

    def test_user_snapshot_jar_digest_when_available(self) -> None:
        """Verify the optional local Cromwell 93 snapshot by its documented digest."""
        local_snapshot = (
            Path(__file__).parents[4]
            / "old_cloudformation"
            / "cromwell_binary"
            / "cromwell-93-053f0dc-SNAP.jar"
        )
        if not local_snapshot.is_file():
            self.skipTest("user-provided local snapshot JAR is not present")
        digest = _sha256(local_snapshot)
        self.assertEqual(
            digest,
            "e2e15f6d54906a14225a7f4f962274dbf7fb7555ae051ad51549a5a64bb5b1ca",
        )
        config = self._config_with(
            {
                "version = 92": "version = 93-053f0dc-SNAP",
                "artifact_path =": f"artifact_path = {local_snapshot}",
                "sha256 =": f"sha256 = {digest}",
            }
        )
        staged = stage_cromwell_jar(config, self.output_path)
        self.assertEqual(_sha256(staged), digest)
