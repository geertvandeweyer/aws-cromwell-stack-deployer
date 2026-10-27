"""Top-level stack for the Cromwell workflow platform."""

from __future__ import annotations

from aws_cdk import CfnOutput, Stack
from constructs import Construct

from cromwell_cdk.config import DeploymentConfig
from cromwell_cdk.constructs.artifacts import ArtifactBucket
from cromwell_cdk.constructs.batch import (
    BatchLaunchTemplate,
    DefaultBatchCompute,
    PriorityBatchCompute,
)
from cromwell_cdk.constructs.cromwell_host import CromwellHost
from cromwell_cdk.constructs.database import MetadataDatabase
from cromwell_cdk.constructs.iam import BatchRoles, CromwellServerRole
from cromwell_cdk.constructs.network import BatchNetwork
from cromwell_cdk.constructs.observability import PlatformLogs
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
        self.logs = PlatformLogs(self, "Logs", config)
        self.launch_template = BatchLaunchTemplate(
            self,
            "BatchLaunchTemplate",
            artifact_bucket_name=self.artifacts.bucket.bucket_name,
            namespace=config.get("deployment", "namespace"),
        )

        self.default_batch = DefaultBatchCompute(
            self,
            "DefaultBatch",
            config=config,
            network=self.network,
            roles=self.iam,
            launch_template=self.launch_template,
        )
        self.priority_batch = PriorityBatchCompute(
            self,
            "PriorityBatch",
            config=config,
            network=self.network,
            roles=self.iam,
            launch_template=self.launch_template,
        )
        CfnOutput(
            self,
            "DataBucketName",
            value=self.data.bucket.bucket_name,
            description="Primary S3 bucket for workflow data",
        )
        CfnOutput(
            self,
            "DefaultQueueName",
            value=self.default_batch.job_queue.job_queue_name,
            description="Default Spot AWS Batch job queue",
        )
        CfnOutput(
            self,
            "PriorityQueueName",
            value=self.priority_batch.job_queue.job_queue_name,
            description="Priority On-Demand AWS Batch job queue",
        )
        CfnOutput(
            self,
            "BatchWorkflowJobRoleArn",
            value=self.iam.job_role.role_arn,
            description=(
                "Set this value as aws_batch_job_role_arn in submitted Cromwell workflow options."
            ),
        )
        cromwell_config = config.section("cromwell")
        database_config = config.section("database")
        self.database = None
        if database_config["hosted"]:
            self.database = MetadataDatabase(
                self,
                "MetadataDatabase",
                config=config,
                vpc=self.network.vpc,
            )
            CfnOutput(
                self,
                "DatabaseSecretArn",
                value=self.database.secret.secret_arn,
                description="Generated Aurora metadata database credentials",
            )
        self.cromwell_role = None
        self.cromwell = None
        if cromwell_config["hosted"]:
            self.cromwell_role = CromwellServerRole(
                self,
                "CromwellServerRole",
                data_bucket=self.data.bucket,
                artifact_bucket=self.artifacts.bucket,
                default_queue_arn=self.default_batch.job_queue.job_queue_arn,
                priority_queue_arn=self.priority_batch.job_queue.job_queue_arn,
                batch_job_role_arn=self.iam.job_role.role_arn,
                log_group_arn=self.logs.cromwell_server.log_group_arn,
                database_secret=self.database.secret if self.database else None,
            )
            self.cromwell = CromwellHost(
                self,
                "CromwellHost",
                config=config,
                network=self.network,
                role=self.cromwell_role,
                database=self.database,
                artifact_bucket=self.artifacts.bucket,
                data_bucket=self.data.bucket,
                server_log_group=self.logs.cromwell_server,
                default_queue=self.default_batch.job_queue,
                priority_queue=self.priority_batch.job_queue,
            )
            CfnOutput(
                self,
                "CromwellEndpoint",
                value=(
                    f"{'https' if config.get('access', 'public_access') else 'http'}://"
                    f"{self.cromwell.load_balancer.load_balancer_dns_name}"
                ),
                description="Cromwell API endpoint",
            )
