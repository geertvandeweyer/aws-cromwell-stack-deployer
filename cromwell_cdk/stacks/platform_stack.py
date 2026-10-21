"""Top-level stack for the Cromwell workflow platform."""

from __future__ import annotations

from aws_cdk import CfnOutput, Stack
from constructs import Construct

from cromwell_cdk.config import DeploymentConfig
from cromwell_cdk.constructs.artifacts import ArtifactBucket
from cromwell_cdk.constructs.network import BatchNetwork


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
    ) -> None:
        super().__init__(scope, construct_id, env=env)
        self.network = BatchNetwork(self, "Network", config)
        self.artifacts = ArtifactBucket(self, "Artifacts", config)
        CfnOutput(
            self,
            "ArtifactBucketName",
            value=self.artifacts.bucket.bucket_name,
            description="Private bucket for repository-owned deployment assets",
        )
