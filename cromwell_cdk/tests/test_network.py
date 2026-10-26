"""Credential-free tests for existing VPC and subnet validation."""

from __future__ import annotations

from pathlib import Path

import aws_cdk as cdk
from aws_cdk import assertions
from cromwell_cdk.stacks.platform_stack import PlatformStack
from cromwell_cdk.config import load_config
from cromwell_cdk.constructs.network import BatchNetwork
from cromwell_cdk.errors import ConfigError, PrereqError
from cromwell_cdk.tests.base import TestBase


ACCOUNT = "123456789012"
REGION = "us-east-1"
VPC_ID = "vpc-0123456789abcdef0"
SUBNET_A = "subnet-aaaaaaaa"
SUBNET_B = "subnet-bbbbbbbb"


def vpc_context(
    subnet_ids: tuple[str, str] = (SUBNET_A, SUBNET_B),
    subnet_azs: tuple[str, str] = ("us-east-1a", "us-east-1b"),
) -> dict[str, object]:
    """Return cached CDK lookup data for private-with-egress subnets.

    Args:
            subnet_ids: Subnet IDs present in the cached private VPC result.
            subnet_azs: Availability Zone for each cached private subnet.

    Returns:
        CDK vpc-provider result accepted by ``Vpc.from_lookup``.
    """
    context_key = (
        f"vpc-provider:account={ACCOUNT}:filter.vpc-id={VPC_ID}:region={REGION}"
        ":returnAsymmetricSubnets=true"
    )
    return {
        context_key: {
            "vpcId": VPC_ID,
            "vpcCidrBlock": "10.0.0.0/16",
            "availabilityZones": list(dict.fromkeys(subnet_azs)),
            "subnetGroups": [
                {
                    "name": "Private",
                    "type": "Private",
                    "subnets": [
                        {
                            "subnetId": subnet_ids[0],
                            "availabilityZone": subnet_azs[0],
                            "routeTableId": "rtb-0123456789abcdef0",
                        },
                        {
                            "subnetId": subnet_ids[1],
                            "availabilityZone": subnet_azs[1],
                            "routeTableId": "rtb-1123456789abcdef0",
                        },
                    ],
                },
            ],
        }
    }


class NetworkTests(TestBase):
    """Validate network subnet selection without contacting AWS."""

    def setUp(self) -> None:
        """Create a valid configuration fixture for each network test."""
        super().setUp()
        self.config_path = Path(self.temp_dir) / "configuration.ini"
        self.config_path.write_text(
            (Path(__file__).parents[2] / "configuration.example.ini").read_text()
        )
        self.config = load_config(self.config_path)

    def make_stack(
        self,
        subnet_azs: tuple[str, str] = ("us-east-1a", "us-east-1b"),
        subnet_ids: tuple[str, str] = (SUBNET_A, SUBNET_B),
    ) -> cdk.Stack:
        """Build an environment-bound stack with cached VPC context.

        Args:
            subnet_azs: Availability Zone for each configured private subnet.

        Returns:
            Stack containing the network construct.
        """
        app = cdk.App(context=vpc_context(subnet_ids, subnet_azs))
        stack = cdk.Stack(app, "TestStack", env={"account": ACCOUNT, "region": REGION})
        BatchNetwork(stack, "Network", self.config)
        return stack

    def test_private_subnets_must_span_distinct_availability_zones(self) -> None:
        """Reject selected private subnets that share an Availability Zone."""
        with self.assertRaisesRegex(ConfigError, "distinct Availability Zones"):
            self.make_stack(("us-east-1a", "us-east-1a"))

    def test_network_synthesizes_with_two_distinct_private_subnets(self) -> None:
        """Synthesize the Batch security group with fixture-backed lookup data."""
        stack = self.make_stack()
        template = assertions.Template.from_stack(stack)
        template.resource_count_is("AWS::EC2::SecurityGroup", 1)
        template.has_resource_properties(
            "AWS::EC2::SecurityGroup",
            {"GroupDescription": "Cromwell Batch compute security group"},
        )

    def test_platform_stack_is_environment_bound_and_synthesizes(self) -> None:
        """Bind platform resources and additional bucket IAM to the deployment."""
        self.config_path.write_text(
            self.config_path.read_text().replace(
                "[additional_s3_buckets]",
                "[additional_s3_buckets]\n"
                "bucket1_name = shared-inputs\n"
                "bucket1_prefix = cohort-a/\n"
                "bucket1_access = readonly",
            )
        )
        self.config = load_config(self.config_path)
        app = cdk.App(context=vpc_context())
        app.node.set_context("cromwellRootBucket", "workflow-data-bucket")
        stack = PlatformStack(
            app,
            "CromwellPlatform",
            config=self.config,
            env={"account": ACCOUNT, "region": REGION},
        )
        template = assertions.Template.from_stack(stack)
        template.has_resource_properties(
            "AWS::EC2::SecurityGroup",
            {"GroupDescription": "Cromwell Batch compute security group"},
        )
        template.has_output("DataBucketName", {})
        template.has_resource_properties(
            "AWS::S3::Bucket",
            {
                "BucketName": "workflow-data-bucket",
                "BucketEncryption": assertions.Match.any_value(),
            },
        )
        policies = template.find_resources("AWS::IAM::Policy")
        rendered_policies = str(policies)
        self.assertIn("shared-inputs/cohort-a/*", rendered_policies)
        self.assertIn("'s3:prefix'", rendered_policies)
        self.assertIn("'s3:GetObject'", rendered_policies)

    def test_adding_bucket_grant_changes_only_iam_policy(self) -> None:
        """Reconcile a config-only grant as IAM without changing other resources."""
        app = cdk.App(context=vpc_context())
        app.node.set_context("cromwellRootBucket", "workflow-data-bucket")
        stack = PlatformStack(
            app,
            "CromwellPlatform",
            config=self.config,
            env={"account": ACCOUNT, "region": REGION},
        )
        baseline = assertions.Template.from_stack(stack).to_json()

        updated_values = {
            **self.config.values,
            "additional_s3_buckets": {
                "1": {
                    "name": "shared-inputs",
                    "prefix": "cohort-a/",
                    "access": "readonly",
                }
            },
        }
        updated_config = type(self.config)(updated_values)
        updated_app = cdk.App(context=vpc_context())
        updated_app.node.set_context("cromwellRootBucket", "workflow-data-bucket")
        updated_stack = PlatformStack(
            updated_app,
            "CromwellPlatform",
            config=updated_config,
            env={"account": ACCOUNT, "region": REGION},
        )
        updated = assertions.Template.from_stack(updated_stack).to_json()

        baseline_resources = baseline.get("Resources", {})
        updated_resources = updated.get("Resources", {})
        changed_resources = {
            logical_id
            for logical_id in baseline_resources.keys() | updated_resources.keys()
            if baseline_resources.get(logical_id) != updated_resources.get(logical_id)
        }
        self.assertEqual(
            changed_resources, {"BatchIamBatchInstanceRoleDefaultPolicy8E105532"}
        )
        self.assertEqual(
            len(baseline.get("Resources", {})),
            len(updated.get("Resources", {})),
        )
        self.assertIn("shared-inputs/cohort-a/*", str(updated))
        self.assertNotIn("shared-inputs", str(baseline))

    def test_configured_subnet_not_in_vpc_fails_as_prerequisite(self) -> None:
        """Reject configured IDs absent from the looked-up private subnet set."""
        with self.assertRaisesRegex(PrereqError, SUBNET_A):
            self.make_stack(subnet_ids=("subnet-cccccccc", SUBNET_B))
