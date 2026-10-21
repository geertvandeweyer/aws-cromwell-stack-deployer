"""Template tests for the private artifact bucket."""

from __future__ import annotations

from pathlib import Path

import aws_cdk as cdk
from aws_cdk import assertions
from cromwell_cdk.config import load_config
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
