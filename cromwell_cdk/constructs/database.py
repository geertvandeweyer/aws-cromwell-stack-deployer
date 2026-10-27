"""Optional Aurora MySQL Serverless v2 metadata database."""

from __future__ import annotations

from aws_cdk import Duration, RemovalPolicy, aws_ec2 as ec2, aws_rds as rds
from constructs import Construct

from cromwell_cdk.config import DeploymentConfig


class MetadataDatabase(Construct):
    """Create a private, TLS-enforced Aurora MySQL Serverless v2 cluster.

    The engine version is fixed by the project design record. AWS availability
    must be confirmed by an RDS orderability query in the deployment region.

    Args:
        scope: Parent construct.
        construct_id: Stable construct identifier.
        config: Validated deployment configuration.
        vpc: VPC in which to create private database instances.

    Raises:
        ValueError: If the configured database engine version is not the
            reviewed project pin.
    """

    ENGINE_VERSION = "8.0.mysql_aurora.3.12.0"

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: DeploymentConfig,
        vpc: ec2.IVpc,
    ) -> None:
        super().__init__(scope, construct_id)
        configured_engine_version = config.get("database", "engine_version")
        if configured_engine_version != self.ENGINE_VERSION:
            raise ValueError(
                "[database] engine_version must use the reviewed pin "
                f"{self.ENGINE_VERSION}"
            )
        removal_policy = {
            "SNAPSHOT": RemovalPolicy.SNAPSHOT,
            "RETAIN": RemovalPolicy.RETAIN,
            "DESTROY": RemovalPolicy.DESTROY,
        }[config.get("database", "removal_policy")]
        self.security_group = ec2.SecurityGroup(
            self,
            "SecurityGroup",
            vpc=vpc,
            description="Cromwell Aurora MySQL security group",
            allow_all_outbound=True,
        )
        self.cluster = rds.DatabaseCluster(
            self,
            "Cluster",
            engine=rds.DatabaseClusterEngine.aurora_mysql(
                version=rds.AuroraMysqlEngineVersion.of(self.ENGINE_VERSION, "8.0")
            ),
            writer=rds.ClusterInstance.serverless_v2("Writer"),
            serverless_v2_min_capacity=config.get("database", "min_acu"),
            serverless_v2_max_capacity=config.get("database", "max_acu"),
            credentials=rds.Credentials.from_generated_secret("cromwell_admin"),
            default_database_name="cromwell",
            parameter_group=rds.ParameterGroup(
                self,
                "ClusterParameters",
                engine=rds.DatabaseClusterEngine.aurora_mysql(
                    version=rds.AuroraMysqlEngineVersion.of(self.ENGINE_VERSION, "8.0")
                ),
                parameters={"require_secure_transport": "ON"},
            ),
            storage_encrypted=True,
            backup=rds.BackupProps(retention=Duration.days(7)),
            deletion_protection=removal_policy != RemovalPolicy.DESTROY,
            removal_policy=removal_policy,
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            security_groups=[self.security_group],
        )
        self.secret = self.cluster.secret
        if self.secret is not None and config.get("database", "rotate_secret"):
            self.cluster.add_rotation_single_user(automatically_after=Duration.days(30))
