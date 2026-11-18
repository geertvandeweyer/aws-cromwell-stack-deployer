"""Credential-free synthesis tests for the dedicated VPC topology."""

from __future__ import annotations

from pathlib import Path

import aws_cdk as cdk
from aws_cdk import assertions
from cromwell_cdk.config import DeploymentConfig, load_config
from cromwell_cdk.constructs.network import BatchNetwork
from cromwell_cdk.stacks.platform_stack import PlatformStack
from cromwell_cdk.tests.base import TestBase


class NetworkTests(TestBase):
    """Verify network resources and subnet selections without AWS lookups."""

    def setUp(self) -> None:
        """Load the checked-in example as a valid network configuration."""
        super().setUp()
        self.config_path = Path(__file__).parents[2] / "configuration.example.ini"
        self.config = load_config(self.config_path)

    def make_network(
        self, *, az_count: str = "3", vpc_cidr: str = "10.0.0.0/16"
    ) -> tuple[assertions.Template, BatchNetwork]:
        """Synthesize a VPC with the requested AZ selection and CIDR."""
        values = {section: dict(items) for section, items in self.config.values.items()}
        values["network"]["availability_zones"] = az_count
        values["network"]["vpc_cidr"] = vpc_cidr
        app = cdk.App()
        stack = cdk.Stack(
            app,
            "NetworkTest",
            env={"account": "123456789012", "region": "us-east-1"},
        )
        network = BatchNetwork(stack, "Network", DeploymentConfig(values))
        return assertions.Template.from_stack(stack), network

    def test_default_network_has_shared_nat_and_s3_endpoint(self) -> None:
        """Create three public/private subnet pairs with one NAT and S3 endpoint."""
        template, network = self.make_network()
        template.resource_count_is("AWS::EC2::VPC", 1)
        template.resource_count_is("AWS::EC2::Subnet", 6)
        template.resource_count_is("AWS::EC2::NatGateway", 1)
        template.resource_count_is("AWS::EC2::VPCEndpoint", 1)
        template.resource_count_is("AWS::EC2::SecurityGroup", 1)
        template.has_resource_properties(
            "AWS::EC2::VPC",
            {"CidrBlock": "10.0.0.0/16", "EnableDnsHostnames": True},
        )
        template.has_resource_properties(
            "AWS::EC2::VPCEndpoint",
            {
                "VpcEndpointType": "Gateway",
                "ServiceName": assertions.Match.any_value(),
            },
        )
        self.assertEqual(len(network.private_subnets), 3)
        self.assertEqual(
            len({subnet.availability_zone for subnet in network.private_subnets}), 3
        )

    def test_two_az_and_custom_cidr_are_supported(self) -> None:
        """Honor an explicit two-AZ count and custom VPC range."""
        template, network = self.make_network(az_count="2", vpc_cidr="10.42.0.0/16")
        template.resource_count_is("AWS::EC2::Subnet", 4)
        template.resource_count_is("AWS::EC2::NatGateway", 1)
        template.has_resource_properties("AWS::EC2::VPC", {"CidrBlock": "10.42.0.0/16"})
        self.assertEqual(len(network.private_subnets), 2)

    def test_max_az_setting_uses_all_account_visible_azs(self) -> None:
        """Use CDK's high max_azs setting for account-visible regional AZs."""
        template, network = self.make_network(az_count="max")
        self.assertGreaterEqual(len(network.private_subnets), 2)
        self.assertEqual(len(network.private_subnets), len(network.vpc.availability_zones))
        template.resource_count_is("AWS::EC2::NatGateway", 1)

    def make_platform(self, config=None) -> assertions.Template:
        """Synthesize the full platform stack with a primary workflow bucket."""
        app = cdk.App()
        app.node.set_context("cromwellRootBucket", "workflow-data-bucket")
        stack = PlatformStack(
            app,
            "CromwellPlatform",
            config=config or self.config,
            env={"account": "123456789012", "region": "us-east-1"},
        )
        return assertions.Template.from_stack(stack)

    def test_default_platform_stack_keeps_host_and_database_opt_in(self) -> None:
        """Create Batch queues and dedicated networking without host/Aurora costs."""
        template = self.make_platform()
        template.resource_count_is("AWS::Batch::JobQueue", 2)
        template.resource_count_is("AWS::EC2::VPC", 1)
        template.resource_count_is("AWS::RDS::DBCluster", 0)
        template.resource_count_is("AWS::EC2::Instance", 0)
        template.resource_count_is("AWS::ElasticLoadBalancingV2::LoadBalancer", 0)
        template.has_output("DefaultQueueName", {})
        template.has_output("PriorityQueueName", {})
        self.assertNotIn("CromwellEndpoint", template.to_json().get("Outputs", {}))

    def test_hosted_cromwell_creates_public_allowlisted_https_alb(self) -> None:
        """Create public TLS ALB, host and SG rules only when hosted is enabled."""
        values = {section: dict(items) for section, items in self.config.values.items()}
        values["cromwell"]["hosted"] = True
        values["cromwell"]["tls_certificate_arn"] = (
            "arn:aws:acm:us-east-1:123456789012:certificate/"
            "12345678-1234-1234-1234-123456789012"
        )
        values["access"]["allowed_cidrs"] = ["203.0.113.0/24"]
        config = DeploymentConfig(values)
        template = self.make_platform(config)
        template.resource_count_is("AWS::EC2::Instance", 1)
        template.resource_count_is("AWS::ElasticLoadBalancingV2::LoadBalancer", 1)
        template.has_output("CromwellEndpoint", {})
        template.has_resource_properties(
            "AWS::ElasticLoadBalancingV2::Listener",
            {
                "Port": 443,
                "Protocol": "HTTPS",
                "Certificates": [
                    {
                        "CertificateArn": values["cromwell"]["tls_certificate_arn"]
                    }
                ],
            },
        )
        security_groups = template.find_resources("AWS::EC2::SecurityGroup")
        lb_security_group = next(
            resource
            for resource in security_groups.values()
            if resource["Properties"].get("GroupDescription")
            == "Cromwell application load balancer security group"
        )
        self.assertIn("203.0.113.0/24", str(lb_security_group))
        self.assertEqual(
            len(lb_security_group["Properties"]["SecurityGroupIngress"]), 1
        )
