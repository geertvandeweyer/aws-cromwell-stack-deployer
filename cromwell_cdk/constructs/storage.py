"""Primary S3 data bucket construct for workflow inputs and outputs."""

from __future__ import annotations

import os
from typing import Any, Protocol

from aws_cdk import RemovalPolicy, aws_s3 as s3
from constructs import Construct

from cromwell_cdk.config import DeploymentConfig
from cromwell_cdk.errors import ConfigError, PrereqError


class S3BucketInspector(Protocol):
    """Read-only subset of the AWS S3 client used for bucket validation."""

    def get_bucket_encryption(self, **kwargs: Any) -> dict[str, Any]:
        """Return a bucket's default encryption configuration."""

    def get_public_access_block(self, **kwargs: Any) -> dict[str, Any]:
        """Return a bucket's public access block configuration."""

    def get_bucket_versioning(self, **kwargs: Any) -> dict[str, Any]:
        """Return a bucket's versioning configuration."""


def validate_existing_bucket(
    bucket_name: str,
    encryption: str,
    inspector: S3BucketInspector | None = None,
) -> None:
    """Verify existing bucket encryption, public access blocking, and versioning.

    Args:
        bucket_name: Existing S3 bucket name to inspect.
        encryption: Required configured encryption (`SSE_KMS` or `SSE_S3`).
        inspector: Optional S3-compatible client, primarily for offline tests.

    Raises:
        ConfigError: If the bucket is missing a required security setting.
        PrereqError: If AWS credentials, permissions, or the bucket are unavailable.
    """
    try:
        if inspector is None:
            import boto3

            region = (
                os.environ.get("AWS_REGION")
                or os.environ.get("AWS_DEFAULT_REGION")
                or os.environ.get("CDK_DEFAULT_REGION")
            )
            inspector = boto3.client("s3", region_name=region)
        encryption_response = inspector.get_bucket_encryption(Bucket=bucket_name)
        public_access_response = inspector.get_public_access_block(Bucket=bucket_name)
        versioning_response = inspector.get_bucket_versioning(Bucket=bucket_name)
    except Exception as exc:
        error_code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
        if error_code in {"AccessDenied", "AccessDeniedException"}:
            raise PrereqError(
                f"Unable to validate existing [storage] bucket {bucket_name!r}; "
                "verify AWS credentials and read-only permissions "
                "(s3:GetEncryptionConfiguration, s3:GetBucketPublicAccessBlock, "
                "s3:GetBucketVersioning): "
                f"{exc}"
            ) from exc
        missing_configuration_errors = {
            "ServerSideEncryptionConfigurationNotFoundError": (
                "bucket default encryption must match configured "
                f"{encryption} ({ {'SSE_KMS': 'aws:kms', 'SSE_S3': 'AES256'}[encryption] })"
            ),
            "NoSuchPublicAccessBlockConfiguration": (
                "public access block must enable BlockPublicAcls, IgnorePublicAcls, "
                "BlockPublicPolicy, RestrictPublicBuckets"
            ),
            "NoSuchBucket": "the configured bucket does not exist",
            "NotFound": "the requested bucket security configuration is missing",
        }
        if error_code in missing_configuration_errors:
            raise ConfigError(
                "Invalid [storage] existing_bucket: "
                f"{missing_configuration_errors[error_code]}"
            ) from exc
        raise PrereqError(
            f"Unable to validate existing [storage] bucket {bucket_name!r}; "
            "verify AWS credentials, s3:GetEncryptionConfiguration, "
            "s3:GetBucketPublicAccessBlock, and s3:GetBucketVersioning permissions: "
            f"{exc}"
        ) from exc

    rules = encryption_response.get("ServerSideEncryptionConfiguration", {}).get(
        "Rules", []
    )
    algorithms = {
        rule.get("ApplyServerSideEncryptionByDefault", {}).get("SSEAlgorithm")
        for rule in rules
    }
    required_algorithm = {"SSE_KMS": "aws:kms", "SSE_S3": "AES256"}[encryption]
    if required_algorithm not in algorithms:
        raise ConfigError(
            "Invalid [storage] existing_bucket: bucket default encryption must "
            f"match configured {encryption} ({required_algorithm})"
        )

    block = public_access_response.get("PublicAccessBlockConfiguration", {})
    required_block_settings = (
        "BlockPublicAcls",
        "IgnorePublicAcls",
        "BlockPublicPolicy",
        "RestrictPublicBuckets",
    )
    missing_block_settings = [
        key for key in required_block_settings if block.get(key) is not True
    ]
    if missing_block_settings:
        raise ConfigError(
            "Invalid [storage] existing_bucket: public access block must enable "
            + ", ".join(missing_block_settings)
        )

    if versioning_response.get("Status") != "Enabled":
        raise ConfigError(
            "Invalid [storage] existing_bucket: bucket versioning must be Enabled"
        )


class DataBucket(Construct):
    """Create the encrypted, versioned, private workflow data bucket.

    Args:
        scope: Parent construct.
        construct_id: Stable construct identifier.
        bucket_name: Globally unique S3 bucket name requested by the operator.
        config: Validated deployment configuration.
        inspector: Optional read-only S3 client used to inspect existing buckets.

    Raises:
        ConfigError: If an adopted bucket does not meet required security settings.
        PrereqError: If AWS cannot inspect the requested existing bucket.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        bucket_name: str,
        config: DeploymentConfig,
        inspector: S3BucketInspector | None = None,
    ) -> None:
        super().__init__(scope, construct_id)
        if config.get("storage", "existing_bucket"):
            validate_existing_bucket(
                bucket_name,
                config.get("storage", "encryption"),
                inspector,
            )
            self.bucket = s3.Bucket.from_bucket_name(self, "Bucket", bucket_name)
            return
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
