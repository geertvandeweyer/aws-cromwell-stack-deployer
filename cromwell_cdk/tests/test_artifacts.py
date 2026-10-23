"""Template tests for the private artifact bucket."""

from __future__ import annotations

from pathlib import Path

import aws_cdk as cdk
from aws_cdk import assertions
from cromwell_cdk.artifact_assets import prepare_artifact_assets
from cromwell_cdk.config import load_config
from cromwell_cdk.errors import ConfigError
from cromwell_cdk.stacks.platform_stack import PlatformStack
from cromwell_cdk.tests.base import TestBase
from cromwell_cdk.tests.test_network import ACCOUNT, REGION, vpc_context


class ArtifactBucketTests(TestBase):
    """Verify security and lifecycle settings for deployment artifacts."""

    def setUp(self) -> None:
        """Load a valid configuration fixture for each test."""
        super().setUp()
        self.config_path = Path(self.temp_dir) / "configuration.ini"
        self.config_path.write_text(
            (Path(__file__).parents[2] / "configuration.example.ini").read_text()
        )
        self.config = load_config(self.config_path)

    def make_template(self) -> assertions.Template:
        """Synthesize the platform stack using cached VPC lookup data.

        Returns:
            CloudFormation template assertions wrapper.
        """
        app = cdk.App(context=vpc_context())
        stack = PlatformStack(
            app,
            "CromwellPlatform",
            config=self.config,
            env={"account": ACCOUNT, "region": REGION},
        )
        return assertions.Template.from_stack(stack)

    def test_artifact_bucket_is_private_encrypted_versioned_and_retained(
        self,
    ) -> None:
        """Require secure defaults and retain the bucket on stack deletion."""
        template = self.make_template()
        template.resource_count_is("AWS::S3::Bucket", 1)
        template.has_resource_properties(
            "AWS::S3::Bucket",
            {
                "PublicAccessBlockConfiguration": {
                    "BlockPublicAcls": True,
                    "BlockPublicPolicy": True,
                    "IgnorePublicAcls": True,
                    "RestrictPublicBuckets": True,
                },
                "BucketEncryption": {
                    "ServerSideEncryptionConfiguration": [
                        {"ServerSideEncryptionByDefault": {"SSEAlgorithm": "aws:kms"}}
                    ]
                },
                "VersioningConfiguration": {"Status": "Enabled"},
            },
        )
        template.has_resource("AWS::S3::Bucket", {"DeletionPolicy": "Retain"})
        template.has_output("ArtifactBucketName", {})

    def test_artifact_bucket_destroy_policy_is_explicitly_configurable(self) -> None:
        """Apply DESTROY only when the artifact removal policy requests it."""
        text = self.config_path.read_text().replace(
            "artifact_bucket_removal_policy = RETAIN",
            "artifact_bucket_removal_policy = DESTROY",
            1,
        )
        self.config_path.write_text(text)
        self.config = load_config(self.config_path)
        template = self.make_template()
        template.has_resource("AWS::S3::Bucket", {"DeletionPolicy": "Delete"})

    def test_verified_assets_deploy_under_dedicated_prefix(self) -> None:
        """Upload reviewed static assets without pruning unrelated keys."""
        asset_path = prepare_artifact_assets(
            self.config, Path(self.temp_dir) / "assembled-assets"
        )
        import hashlib

        manifest_entries = {
            filename: digest
            for digest, filename in (
                line.split(maxsplit=1)
                for line in (asset_path / "CHECKSUMS.sha256")
                .read_text(encoding="utf-8")
                .splitlines()
            )
        }
        self.assertTrue(manifest_entries)
        self.assertEqual(
            set(manifest_entries),
            {
                path.name
                for path in asset_path.iterdir()
                if path.name != "CHECKSUMS.sha256"
            },
        )
        for filename, expected_digest in manifest_entries.items():
            actual_digest = hashlib.sha256(
                (asset_path / filename).read_bytes()
            ).hexdigest()
            self.assertEqual(actual_digest, expected_digest, filename)

        app = cdk.App(context=vpc_context())
        stack = PlatformStack(
            app,
            "CromwellPlatform",
            config=self.config,
            env={"account": ACCOUNT, "region": REGION},
            artifact_assets_path=str(asset_path),
        )
        template = assertions.Template.from_stack(stack)
        template.resource_count_is("Custom::CDKBucketDeployment", 1)
        template.has_resource_properties(
            "Custom::CDKBucketDeployment",
            {
                "DestinationBucketKeyPrefix": "assets",
                "Prune": False,
                "RetainOnDelete": True,
            },
        )

    def test_hosted_asset_assembly_includes_verified_jar(self) -> None:
        """Only hosted configurations stage and manifest the configured JAR."""
        import hashlib

        source_path = Path(self.temp_dir) / "local.jar"
        source_path.write_bytes(b"test Cromwell jar")
        digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
        text = (
            self.config_path.read_text()
            .replace("hosted = false", "hosted = true", 1)
            .replace("artifact_path =", f"artifact_path = {source_path}", 1)
        )
        text = text.replace("sha256 =", f"sha256 = {digest}", 1)
        self.config_path.write_text(text)
        self.config = load_config(self.config_path)
        assembled = prepare_artifact_assets(
            self.config, Path(self.temp_dir) / "hosted-assets"
        )
        self.assertEqual(
            (assembled / "cromwell.jar").read_bytes(), source_path.read_bytes()
        )
        manifest = (assembled / "CHECKSUMS.sha256").read_text()
        self.assertIn(f"{digest}  cromwell.jar", manifest)
        self.assertIn("fetch_and_run.sh", manifest)

    def test_non_hosted_assembly_does_not_stage_jar(self) -> None:
        """Avoid local source access or remote downloads when hosted is disabled."""
        from unittest.mock import patch

        with patch("cromwell_cdk.artifact_assets.stage_cromwell_jar") as stage:
            assembled = prepare_artifact_assets(
                self.config, Path(self.temp_dir) / "non-hosted-assets"
            )
        stage.assert_not_called()
        self.assertFalse((assembled / "cromwell.jar").exists())

    def test_static_asset_checksum_mismatch_fails_closed(self) -> None:
        """Do not package modified static assets against a stale manifest."""
        from unittest.mock import patch

        fixture_assets = Path(self.temp_dir) / "source-assets"
        fixture_assets.mkdir()
        (fixture_assets / "CHECKSUMS.sha256").write_text(
            "0" * 64 + "  fetch_and_run.sh\n"
        )
        (fixture_assets / "fetch_and_run.sh").write_text("modified")
        with patch("cromwell_cdk.artifact_assets.ASSET_DIRECTORY", fixture_assets):
            with self.assertRaisesRegex(ConfigError, "checksum mismatch"):
                prepare_artifact_assets(
                    self.config, Path(self.temp_dir) / "invalid-assets"
                )

    def test_checksum_mismatch_prevents_stack_synthesis(self) -> None:
        """Reject corrupt source assets before constructing the deployment stack."""
        from unittest.mock import patch

        fixture_assets = Path(self.temp_dir) / "corrupt-source-assets"
        fixture_assets.mkdir()
        (fixture_assets / "CHECKSUMS.sha256").write_text(
            "0" * 64 + "  fetch_and_run.sh\n", encoding="utf-8"
        )
        (fixture_assets / "fetch_and_run.sh").write_text("tampered", encoding="utf-8")

        with patch("cromwell_cdk.artifact_assets.ASSET_DIRECTORY", fixture_assets):
            with self.assertRaisesRegex(ConfigError, "checksum mismatch"):
                asset_path = prepare_artifact_assets(
                    self.config, Path(self.temp_dir) / "rejected-assets"
                )
                app = cdk.App(context=vpc_context())
                PlatformStack(
                    app,
                    "CromwellPlatform",
                    config=self.config,
                    env={"account": ACCOUNT, "region": REGION},
                    artifact_assets_path=str(asset_path),
                )
                app.synth()

    def test_unmanifested_static_asset_fails_closed(self) -> None:
        """Reject new files until their reviewed digest is added to the manifest."""
        from unittest.mock import patch

        fixture_assets = Path(self.temp_dir) / "source-assets"
        fixture_assets.mkdir()
        (fixture_assets / "CHECKSUMS.sha256").write_text("")
        (fixture_assets / "fetch_and_run.sh").write_text("unmanifested")
        with patch("cromwell_cdk.artifact_assets.ASSET_DIRECTORY", fixture_assets):
            with self.assertRaisesRegex(ConfigError, "does not match"):
                prepare_artifact_assets(
                    self.config, Path(self.temp_dir) / "invalid-assets"
                )
