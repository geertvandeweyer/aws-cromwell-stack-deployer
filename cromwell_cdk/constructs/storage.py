"""Primary S3 data bucket construct for workflow inputs and outputs."""

from __future__ import annotations

from aws_cdk import RemovalPolicy, aws_s3 as s3
from constructs import Construct

from cromwell_cdk.config import DeploymentConfig
from cromwell_cdk.errors import ConfigError


class DataBucket(Construct):
    """Create the encrypted, versioned, private workflow data bucket.

    Args:
        scope: Parent construct.
        construct_id: Stable construct identifier.
        bucket_name: Globally unique S3 bucket name requested by the operator.
        config: Validated deployment configuration.

    Raises:
        ConfigError: If existing-bucket adoption is requested before it is implemented.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        bucket_name: str,
        config: DeploymentConfig,
    ) -> None:
        super().__init__(scope, construct_id)
        if config.get("storage", "existing_bucket"):
            raise ConfigError(
                "Invalid [storage] existing_bucket: existing-bucket validation is not implemented"
            )

        encryption = {
            "SSE_KMS": s3.BucketEncryption.KMS_MANAGED,
            "SSE_S3": s3.BucketEncryption.S3_MANAGED,
        }[config.get("storage", "encryption")]
        removal_policy = (
            RemovalPolicy.DESTROY
            if config.get("storage", "removal_policy") == "DESTROY"
            else RemovalPolicy.RETAIN
        )
        self.bucket = s3.Bucket(
            self,
            "Bucket",
            bucket_name=bucket_name,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=encryption,
            enforce_ssl=True,
            versioned=True,
            removal_policy=removal_policy,
        )
