"""Private S3 artifact bucket for repository-owned deployment assets."""

from __future__ import annotations

from aws_cdk import RemovalPolicy, aws_s3 as s3
from constructs import Construct

from cromwell_cdk.config import DeploymentConfig


class ArtifactBucket(Construct):
    """Create the encrypted, versioned, private artifact bucket.

    Args:
        scope: Parent construct.
        construct_id: Stable construct identifier.
        config: Validated deployment configuration.
    """

    def __init__(
        self, scope: Construct, construct_id: str, config: DeploymentConfig
    ) -> None:
        super().__init__(scope, construct_id)
        removal_policy = (
            RemovalPolicy.DESTROY
            if config.get("artifacts", "artifact_bucket_removal_policy") == "DESTROY"
            else RemovalPolicy.RETAIN
        )
        self.bucket = s3.Bucket(
            self,
            "Bucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.KMS,
            enforce_ssl=True,
            versioned=True,
            removal_policy=removal_policy,
        )
