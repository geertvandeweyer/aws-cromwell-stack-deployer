"""Existing-network lookup and Batch security group construction."""

from __future__ import annotations

from aws_cdk import aws_ec2 as ec2
from constructs import Construct

from cromwell_cdk.config import DeploymentConfig
from cromwell_cdk.errors import ConfigError, PrereqError


class BatchNetwork(Construct):
    """Look up the configured VPC and create its default Batch security group.

    Args:
        scope: Parent construct.
        construct_id: Stable construct identifier.
        config: Validated deployment configuration.

    Raises:
        ConfigError: If configured private subnets are absent or not in distinct AZs.
        PrereqError: If the VPC lookup does not yield its configured private subnets.
    """

    def __init__(
        self, scope: Construct, construct_id: str, config: DeploymentConfig
    ) -> None:
        super().__init__(scope, construct_id)
        vpc_id = config.get("network", "vpc_id")
        configured_subnet_ids = config.get("network", "private_subnet_ids")
        self.vpc = ec2.Vpc.from_lookup(
            self,
            "ExistingVpc",
            vpc_id=vpc_id,
        )

        private_subnets = {
            subnet.subnet_id: subnet for subnet in self.vpc.private_subnets
        }
        missing_subnets = sorted(set(configured_subnet_ids) - set(private_subnets))
        if missing_subnets:
            missing = ", ".join(missing_subnets)
            raise PrereqError(
                f"Configured private subnet(s) not found in VPC {vpc_id}: {missing}"
            )

        selected_subnets = [
            private_subnets[subnet_id] for subnet_id in configured_subnet_ids
        ]
        availability_zones = [subnet.availability_zone for subnet in selected_subnets]
        if len(set(availability_zones)) != len(availability_zones):
            raise ConfigError(
                "Invalid [network] private_subnet_ids: selected subnets must span distinct Availability Zones"
            )
        self.security_group = ec2.SecurityGroup(
            self,
            "BatchSecurityGroup",
            vpc=self.vpc,
            description="Cromwell Batch compute security group",
            allow_all_outbound=True,
        )
