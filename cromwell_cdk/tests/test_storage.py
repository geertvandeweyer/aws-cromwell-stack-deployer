"""Template tests for the primary workflow data bucket."""

from __future__ import annotations

from pathlib import Path

import aws_cdk as cdk
from aws_cdk import assertions

from cromwell_cdk.config import load_config
from cromwell_cdk.constructs.storage import DataBucket
from cromwell_cdk.errors import ConfigError
from cromwell_cdk.tests.base import TestBase


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

    def test_existing_bucket_mode_fails_closed_until_validated(self) -> None:
        """Do not silently create or trust an existing bucket before validation exists."""
        text = self.config_path.read_text().replace(
            "existing_bucket = false", "existing_bucket = true", 1
        )
        self.config_path.write_text(text)
        self.config = load_config(self.config_path)
        app = cdk.App()
        stack = cdk.Stack(app, "StorageTestStack")
        with self.assertRaisesRegex(ConfigError, r"\[storage\] existing_bucket"):
            DataBucket(
                stack,
                "Data",
                bucket_name="cromwell-data-test-bucket",
                config=self.config,
            )
