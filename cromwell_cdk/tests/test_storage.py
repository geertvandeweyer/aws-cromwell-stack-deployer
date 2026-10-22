"""Template tests for the primary workflow data bucket."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import aws_cdk as cdk
from aws_cdk import assertions

from cromwell_cdk.config import load_config
from cromwell_cdk.constructs.storage import DataBucket
from cromwell_cdk.errors import ConfigError, PrereqError
from cromwell_cdk.tests.base import TestBase


class S3ApiError(RuntimeError):
    """Mock AWS error exposing the response shape used by botocore."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class DataBucketTests(TestBase):
    """Verify data-bucket security settings and lifecycle behavior."""

    def setUp(self) -> None:
        """Load a valid configuration fixture for each test."""
        super().setUp()
        self.config_path = Path(self.temp_dir) / "configuration.ini"
        self.config_path.write_text(
            (Path(__file__).parents[2] / "configuration.example.ini").read_text()
        )
        self.config = load_config(self.config_path)

    def make_template(self) -> assertions.Template:
        """Synthesize a standalone data bucket.

        Returns:
            CloudFormation template assertions wrapper.
        """
        app = cdk.App()
        stack = cdk.Stack(app, "StorageTestStack")
        DataBucket(
            stack,
            "Data",
            bucket_name="cromwell-data-test-bucket",
            config=self.config,
        )
        return assertions.Template.from_stack(stack)

    def test_bucket_is_private_versioned_tls_only_and_retained(self) -> None:
        """Apply secure defaults and retain data on stack deletion."""
        template = self.make_template()
        template.resource_count_is("AWS::S3::Bucket", 1)
        template.has_resource_properties(
            "AWS::S3::Bucket",
            {
                "BucketName": "cromwell-data-test-bucket",
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
        template.has_resource_properties(
            "AWS::S3::BucketPolicy",
            {
                "PolicyDocument": {
                    "Statement": assertions.Match.array_with(
                        [
                            assertions.Match.object_like(
                                {
                                    "Effect": "Deny",
                                    "Principal": {"AWS": "*"},
                                    "Action": "s3:*",
                                    "Condition": {
                                        "Bool": {"aws:SecureTransport": "false"}
                                    },
                                }
                            )
                        ]
                    )
                }
            },
        )

    def test_s3_managed_encryption_and_destroy_are_explicit_options(self) -> None:
        """Honor configured SSE-S3 encryption and DESTROY lifecycle choices."""
        text = self.config_path.read_text().replace(
            "encryption = SSE_KMS", "encryption = SSE_S3", 1
        )
        text = text.replace("removal_policy = RETAIN", "removal_policy = DESTROY", 1)
        self.config_path.write_text(text)
        self.config = load_config(self.config_path)

        template = self.make_template()
        template.has_resource_properties(
            "AWS::S3::Bucket",
            {
                "BucketEncryption": {
                    "ServerSideEncryptionConfiguration": [
                        {"ServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}
                    ]
                }
            },
        )
        template.has_resource("AWS::S3::Bucket", {"DeletionPolicy": "Delete"})

    def test_existing_bucket_mode_adopts_compatible_bucket_without_creating_it(
        self,
    ) -> None:
        """Import a bucket only after its configured security properties pass."""
        text = self.config_path.read_text().replace(
            "existing_bucket = false", "existing_bucket = true", 1
        )
        self.config_path.write_text(text)
        self.config = load_config(self.config_path)
        app = cdk.App()
        stack = cdk.Stack(app, "StorageTestStack")
        inspector = Mock()
        inspector.get_bucket_encryption.return_value = {
            "ServerSideEncryptionConfiguration": {
                "Rules": [
                    {"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "aws:kms"}}
                ]
            }
        }
        inspector.get_public_access_block.return_value = {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "IgnorePublicAcls": True,
                "BlockPublicPolicy": True,
                "RestrictPublicBuckets": True,
            }
        }
        inspector.get_bucket_versioning.return_value = {"Status": "Enabled"}

        DataBucket(
            stack,
            "Data",
            bucket_name="cromwell-data-test-bucket",
            config=self.config,
            inspector=inspector,
        )
        template = assertions.Template.from_stack(stack)
        template.resource_count_is("AWS::S3::Bucket", 0)
        inspector.get_bucket_encryption.assert_called_once_with(
            Bucket="cromwell-data-test-bucket"
        )
        inspector.get_public_access_block.assert_called_once_with(
            Bucket="cromwell-data-test-bucket"
        )
        inspector.get_bucket_versioning.assert_called_once_with(
            Bucket="cromwell-data-test-bucket"
        )

    def _existing_bucket_config(self, encryption: str = "SSE_KMS"):
        """Enable existing-bucket mode with a selected encryption requirement."""
        text = self.config_path.read_text().replace(
            "existing_bucket = false", "existing_bucket = true", 1
        )
        text = text.replace("encryption = SSE_KMS", f"encryption = {encryption}", 1)
        self.config_path.write_text(text)
        self.config = load_config(self.config_path)
        return self.config

    def _secure_bucket_inspector(self, algorithm: str = "aws:kms") -> Mock:
        """Return mocked S3 responses meeting all adoption security conditions."""
        inspector = Mock()
        inspector.get_bucket_encryption.return_value = {
            "ServerSideEncryptionConfiguration": {
                "Rules": [
                    {"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": algorithm}}
                ]
            }
        }
        inspector.get_public_access_block.return_value = {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "IgnorePublicAcls": True,
                "BlockPublicPolicy": True,
                "RestrictPublicBuckets": True,
            }
        }
        inspector.get_bucket_versioning.return_value = {"Status": "Enabled"}
        return inspector

    def test_existing_bucket_requires_configured_encryption_mode(self) -> None:
        """Require adopted-bucket encryption to match configured SSE mode."""
        config = self._existing_bucket_config("SSE_S3")
        inspector = self._secure_bucket_inspector("aws:kms")
        stack = cdk.Stack(cdk.App(), "StorageTestStack")
        with self.assertRaisesRegex(ConfigError, "must match configured SSE_S3"):
            DataBucket(
                stack,
                "Data",
                bucket_name="cromwell-data-test-bucket",
                config=config,
                inspector=inspector,
            )

    def test_existing_bucket_accepts_configured_sse_s3_encryption(self) -> None:
        """Adopt a bucket using AES256 when SSE_S3 is configured."""
        config = self._existing_bucket_config("SSE_S3")
        inspector = self._secure_bucket_inspector("AES256")
        stack = cdk.Stack(cdk.App(), "StorageTestStack")
        DataBucket(
            stack,
            "Data",
            bucket_name="cromwell-data-test-bucket",
            config=config,
            inspector=inspector,
        )
        assertions.Template.from_stack(stack).resource_count_is("AWS::S3::Bucket", 0)

    def test_existing_bucket_requires_all_public_access_block_settings(self) -> None:
        """Reject adopted buckets missing any required public access block flag."""
        config = self._existing_bucket_config()
        inspector = self._secure_bucket_inspector()
        inspector.get_public_access_block.return_value[
            "PublicAccessBlockConfiguration"
        ]["RestrictPublicBuckets"] = False
        stack = cdk.Stack(cdk.App(), "StorageTestStack")
        with self.assertRaisesRegex(ConfigError, "RestrictPublicBuckets"):
            DataBucket(
                stack,
                "Data",
                bucket_name="cromwell-data-test-bucket",
                config=config,
                inspector=inspector,
            )

    def test_existing_bucket_requires_enabled_versioning(self) -> None:
        """Reject adopted buckets when versioning is absent or suspended."""
        config = self._existing_bucket_config()
        inspector = self._secure_bucket_inspector()
        inspector.get_bucket_versioning.return_value = {"Status": "Suspended"}
        stack = cdk.Stack(cdk.App(), "StorageTestStack")
        with self.assertRaisesRegex(ConfigError, "versioning must be Enabled"):
            DataBucket(
                stack,
                "Data",
                bucket_name="cromwell-data-test-bucket",
                config=config,
                inspector=inspector,
            )

    def test_existing_bucket_access_denied_is_prerequisite_error(self) -> None:
        """Fail closed with actionable permissions when AWS denies inspection."""
        config = self._existing_bucket_config()
        inspector = self._secure_bucket_inspector()
        inspector.get_bucket_encryption.side_effect = S3ApiError("AccessDenied")
        stack = cdk.Stack(cdk.App(), "StorageTestStack")
        with self.assertRaisesRegex(PrereqError, "s3:GetEncryptionConfiguration"):
            DataBucket(
                stack,
                "Data",
                bucket_name="cromwell-data-test-bucket",
                config=config,
                inspector=inspector,
            )

    def test_existing_bucket_without_default_encryption_is_configuration_error(
        self,
    ) -> None:
        """Classify an S3 response lacking default encryption as incompatible."""
        config = self._existing_bucket_config()
        inspector = self._secure_bucket_inspector()
        inspector.get_bucket_encryption.side_effect = S3ApiError(
            "ServerSideEncryptionConfigurationNotFoundError"
        )
        stack = cdk.Stack(cdk.App(), "StorageTestStack")
        with self.assertRaisesRegex(ConfigError, "bucket default encryption"):
            DataBucket(
                stack,
                "Data",
                bucket_name="cromwell-data-test-bucket",
                config=config,
                inspector=inspector,
            )

    def test_existing_bucket_without_public_access_block_is_configuration_error(
        self,
    ) -> None:
        """Classify a missing S3 public-access-block configuration as incompatible."""
        config = self._existing_bucket_config()
        inspector = self._secure_bucket_inspector()
        inspector.get_public_access_block.side_effect = S3ApiError(
            "NoSuchPublicAccessBlockConfiguration"
        )
        stack = cdk.Stack(cdk.App(), "StorageTestStack")
        with self.assertRaisesRegex(ConfigError, "public access block must enable"):
            DataBucket(
                stack,
                "Data",
                bucket_name="cromwell-data-test-bucket",
                config=config,
                inspector=inspector,
            )

    def test_nonexistent_existing_bucket_is_configuration_error(self) -> None:
        """Classify a missing named bucket as invalid existing-bucket input."""
        config = self._existing_bucket_config()
        inspector = self._secure_bucket_inspector()
        inspector.get_bucket_encryption.side_effect = S3ApiError("NoSuchBucket")
        stack = cdk.Stack(cdk.App(), "StorageTestStack")
        with self.assertRaisesRegex(ConfigError, "configured bucket does not exist"):
            DataBucket(
                stack,
                "Data",
                bucket_name="missing-cromwell-data-bucket",
                config=config,
                inspector=inspector,
            )
