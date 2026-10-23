"""Top-level stack for the Cromwell workflow platform."""

from __future__ import annotations

from aws_cdk import CfnOutput, Stack
from constructs import Construct

from cromwell_cdk.config import DeploymentConfig
from cromwell_cdk.constructs.artifacts import ArtifactBucket
from cromwell_cdk.constructs.iam import BatchRoles
from cromwell_cdk.constructs.network import BatchNetwork
from cromwell_cdk.constructs.storage import DataBucket


class PlatformStack(Stack):
    """Create platform foundation resources from validated configuration.

    Args:
        scope: Parent construct.
        construct_id: Stable stack identifier.
        config: Validated deployment configuration.
        env: Concrete target account and region used by VPC lookup.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: DeploymentConfig,
        env: dict[str, str],
        artifact_assets_path: str | None = None,
    ) -> None:
        super().__init__(scope, construct_id, env=env)
        self.network = BatchNetwork(self, "Network", config)
        self.artifacts = ArtifactBucket(
            self, "Artifacts", config, asset_directory=artifact_assets_path
        )
        CfnOutput(
            self,
            "ArtifactBucketName",
            value=self.artifacts.bucket.bucket_name,
            description="Private bucket for repository-owned deployment assets",
        )
        data_bucket_name = self.node.try_get_context("cromwellRootBucket")
        if not data_bucket_name:
            return
        self.data = DataBucket(
            self,
            "Data",
            bucket_name=str(data_bucket_name),
            config=config,
        )
        self.iam = BatchRoles(
            self,
            "BatchIam",
            artifact_bucket=self.artifacts.bucket,
            data_bucket=self.data.bucket,
            additional_s3_grants=config.section("additional_s3_buckets"),
        )
        CfnOutput(
            self,
            "DataBucketName",
            value=self.data.bucket.bucket_name,
            description="Primary S3 bucket for workflow data",
        )
