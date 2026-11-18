"""Dedicated VPC, subnet, endpoint, and Batch security group construction."""

from __future__ import annotations

from aws_cdk import aws_ec2 as ec2
from constructs import Construct

from cromwell_cdk.config import DeploymentConfig
class BatchNetwork(Construct):
    """Create a dedicated VPC with public/private subnets and shared egress.

    Args:
        scope: Parent construct.
        construct_id: Stable construct identifier.
        config: Validated deployment configuration.

    Raises:
        ValueError: If the region has fewer than two available AZs.
    """

    def __init__(
        self, scope: Construct, construct_id: str, config: DeploymentConfig
    ) -> None:
        super().__init__(scope, construct_id)
        az_setting = str(config.get("network", "availability_zones")).lower()
        max_azs = 99 if az_setting == "max" else int(az_setting)
        self.vpc = ec2.Vpc(
            self,
            "Vpc",
            ip_addresses=ec2.IpAddresses.cidr(config.get("network", "vpc_cidr")),
            max_azs=max_azs,
            nat_gateways=1,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    name="Private",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=21,
                ),
            ],
            gateway_endpoints={
                "S3": ec2.GatewayVpcEndpointOptions(
                    service=ec2.GatewayVpcEndpointAwsService.S3,
                )
            },
            vpc_name=f"{config.get('deployment', 'namespace')}-vpc",
        )
        self.private_subnets = self.vpc.private_subnets
        self.private_subnet_ids = [
            subnet.subnet_id for subnet in self.private_subnets
        ]
        self.security_group = ec2.SecurityGroup(
            self,
            "BatchSecurityGroup",
            vpc=self.vpc,
            description="Cromwell Batch compute security group",
            allow_all_outbound=True,
        )
