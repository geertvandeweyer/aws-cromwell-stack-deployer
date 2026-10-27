"""Synthesis tests for secure Batch launch-template defaults."""

from __future__ import annotations

from pathlib import Path

import aws_cdk as cdk
from aws_cdk import assertions, aws_s3 as s3
from cromwell_cdk.config import load_config
from cromwell_cdk.constructs.batch import (
    BatchLaunchTemplate,
    DefaultBatchCompute,
    PriorityBatchCompute,
)
from cromwell_cdk.constructs.iam import BatchRoles
from cromwell_cdk.constructs.network import BatchNetwork
from cromwell_cdk.tests.base import TestBase


ACCOUNT = "123456789012"
REGION = "us-east-1"
VPC_ID = "vpc-0123456789abcdef0"
SUBNET_A = "subnet-aaaaaaaa"
SUBNET_B = "subnet-bbbbbbbb"


def vpc_context() -> dict[str, object]:
    """Return cached CDK lookup data for two private Batch subnets.

    Returns:
        VPC provider context accepted by ``Vpc.from_lookup``.
    """
    context_key = (
        f"vpc-provider:account={ACCOUNT}:filter.vpc-id={VPC_ID}:region={REGION}"
        ":returnAsymmetricSubnets=true"
    )
    return {
        context_key: {
            "vpcId": VPC_ID,
            "vpcCidrBlock": "10.0.0.0/16",
            "availabilityZones": ["us-east-1a", "us-east-1b"],
            "subnetGroups": [
                {
                    "name": "Private",
                    "type": "Private",
                    "subnets": [
                        {
                            "subnetId": SUBNET_A,
                            "availabilityZone": "us-east-1a",
                            "routeTableId": "rtb-0123456789abcdef0",
                        },
                        {
                            "subnetId": SUBNET_B,
                            "availabilityZone": "us-east-1b",
                            "routeTableId": "rtb-1123456789abcdef0",
                        },
                    ],
                },
            ],
        }
    }


class BatchLaunchTemplateTests(TestBase):
    """Verify AMI-neutral, encrypted, IMDSv2 launch-template settings."""

    def test_template_encrypts_shared_root_and_docker_volume(self) -> None:
        """Synthesize secure metadata and the shared AL2023 data volume."""
        app = cdk.App()
        stack = cdk.Stack(app, "BatchLaunchTemplateTest")
        batch_template = BatchLaunchTemplate(
            stack,
            "BatchLaunchTemplate",
            artifact_bucket_name="private-assets",
            namespace="cromwell-prod",
        )
        template = assertions.Template.from_stack(stack)

        template.has_resource_properties(
            "AWS::EC2::LaunchTemplate",
            {
                "LaunchTemplateData": {
                    "MetadataOptions": {
                        "HttpEndpoint": "enabled",
                        "HttpTokens": "required",
                        "HttpPutResponseHopLimit": 1,
                    },
                    "BlockDeviceMappings": [
                        {
                            "DeviceName": "/dev/xvda",
                            "Ebs": {
                                "Encrypted": True,
                                "VolumeSize": 100,
                                "VolumeType": "gp3",
                                "DeleteOnTermination": True,
                            },
                        }
                    ],
                }
            },
        )
        rendered = str(template.to_json())
        self.assertIn("multipart/mixed", rendered)
        self.assertIn(
            "awscli.amazonaws.com/awscli-exe-linux-${AWS_CLI_ARCH}.zip", rendered
        )
        self.assertIn("sha256sum --check CHECKSUMS.sha256", rendered)
        self.assertIn("ARTIFACTS_NAMESPACE=cromwell-prod", rendered)
        self.assertIn("provision.sh", rendered)
        self.assertIn("cromwell-prod", rendered)
        self.assertLess(
            rendered.index("aws/install --install-dir"),
            rendered.index('"$AWS" s3 cp'),
        )
        self.assertNotIn('"ImageId"', rendered)
        self.assertIsNotNone(batch_template.launch_template)

    def test_template_accepts_batch_compatible_multipart_user_data(self) -> None:
        """Preserve caller MIME content in the launch-template resource."""
        user_data = (
            "MIME-Version: 1.0\n"
            'Content-Type: multipart/mixed; boundary="==CUSTOM=="\n\n'
            "--==CUSTOM==\n"
            'Content-Type: text/x-shellscript; charset="us-ascii"\n\n'
            "#!/bin/bash\nprintf 'bootstrap\\n'\n"
            "--==CUSTOM==--\n"
        )
        app = cdk.App()
        stack = cdk.Stack(app, "BatchUserDataTest")
        BatchLaunchTemplate(stack, "BatchLaunchTemplate", user_data=user_data)
        template = assertions.Template.from_stack(stack)

        template.has_resource_properties(
            "AWS::EC2::LaunchTemplate",
            {
                "LaunchTemplateData": {
                    "UserData": assertions.Match.any_value(),
                    "MetadataOptions": {
                        "HttpTokens": "required",
                        "HttpPutResponseHopLimit": 1,
                    },
                }
            },
        )
        self.assertIn("CUSTOM", str(template.to_json()))

    def make_compute_template(
        self, *, spot: bool = True
    ) -> tuple[assertions.Template, DefaultBatchCompute]:
        """Synthesize Batch compute resources using a fixture-backed VPC.

        Args:
            spot: Whether the default environment should use Spot capacity.

        Returns:
            Synthesized template and the default Batch compute construct.
        """
        config_path = Path(self.temp_dir) / "configuration.ini"
        config_text = (
            Path(__file__).parents[2] / "configuration.example.ini"
        ).read_text()
        if not spot:
            config_text = config_text.replace(
                "default_use_spot = true", "default_use_spot = false"
            )
        config_path.write_text(config_text)
        config = load_config(config_path)

        app = cdk.App(context=vpc_context())
        stack = cdk.Stack(
            app, "DefaultBatchComputeTest", env={"account": ACCOUNT, "region": REGION}
        )
        network = BatchNetwork(stack, "Network", config)
        artifact_bucket = s3.Bucket(stack, "ArtifactBucket")
        data_bucket = s3.Bucket(stack, "DataBucket")
        roles = BatchRoles(
            stack,
            "Roles",
            artifact_bucket=artifact_bucket,
            data_bucket=data_bucket,
        )
        launch_template = BatchLaunchTemplate(stack, "LaunchTemplate")
        compute = DefaultBatchCompute(
            stack,
            "DefaultBatch",
            config=config,
            network=network,
            roles=roles,
            launch_template=launch_template,
        )
        PriorityBatchCompute(
            stack,
            "PriorityBatch",
            config=config,
            network=network,
            roles=roles,
            launch_template=launch_template,
        )
        return assertions.Template.from_stack(stack), compute

    def test_default_compute_environment_uses_spot_and_configured_resources(
        self,
    ) -> None:
        """Use the configured capacity, selected network, and managed AL2023 image."""
        template, compute = self.make_compute_template()
        template.has_resource_properties(
            "AWS::Batch::ComputeEnvironment",
            {
                "Type": "managed",
                "ComputeResources": {
                    "Type": "SPOT",
                    "MinvCpus": 0,
                    "MaxvCpus": 256,
                    "InstanceTypes": ["m5.large", "m5.xlarge"],
                    "BidPercentage": 100,
                    "Subnets": [SUBNET_A, SUBNET_B],
                    "SecurityGroupIds": [assertions.Match.any_value()],
                    "LaunchTemplate": assertions.Match.any_value(),
                },
                "ServiceRole": assertions.Match.any_value(),
            },
        )
        resources = template.find_resources("AWS::Batch::ComputeEnvironment")
        default_environment = next(
            (
                resource
                for resource in resources.values()
                if resource["Properties"]["ComputeResources"]["Type"] == "SPOT"
            )
        )
        rendered = str(resources)
        self.assertIn("ECS_AL2023", rendered)
        instance_profile = next(
            iter(template.find_resources("AWS::IAM::InstanceProfile").values())
        )
        self.assertEqual(len(instance_profile["Properties"]["Roles"]), 1)
        roles = template.find_resources("AWS::IAM::Role")
        instance_role_id = next(
            logical_id
            for logical_id, role in roles.items()
            if role["Properties"]["AssumeRolePolicyDocument"]["Statement"][0][
                "Principal"
            ]["Service"]
            == "ec2.amazonaws.com"
        )
        self.assertEqual(
            instance_profile["Properties"]["Roles"], [{"Ref": instance_role_id}]
        )
        queues = template.find_resources("AWS::Batch::JobQueue")
        self.assertEqual(len(queues), 2)
        template.has_resource_properties(
            "AWS::Batch::JobQueue",
            {
                "Priority": 1,
                "ComputeEnvironmentOrder": [
                    {"Order": 1, "ComputeEnvironment": assertions.Match.any_value()}
                ],
            },
        )
        queue_resources = queues
        queue = next(
            resource["Properties"]
            for resource in queue_resources.values()
            if resource["Properties"]["Priority"] == 1
        )
        environment = default_environment
        self.assertEqual(
            queue["ComputeEnvironmentOrder"][0]["ComputeEnvironment"],
            {
                "Fn::GetAtt": [
                    next(
                        logical_id
                        for logical_id, resource in resources.items()
                        if resource is default_environment
                    ),
                    "ComputeEnvironmentArn",
                ]
            },
        )
        self.assertEqual(
            environment["Properties"]["ComputeResources"]["InstanceTypes"],
            ["m5.large", "m5.xlarge"],
        )
        self.assertIsNotNone(compute.compute_environment)
        self.assertIsNotNone(compute.job_queue)

    def test_on_demand_environment_omits_spot_bid_setting(self) -> None:
        """Do not attach Spot-only properties to an On-Demand environment."""
        template, _ = self.make_compute_template(spot=False)
        environment = next(
            resource
            for resource in template.find_resources(
                "AWS::Batch::ComputeEnvironment"
            ).values()
            if resource["Properties"]["ComputeResources"]["Type"] == "EC2"
        )
        compute_resources = environment["Properties"]["ComputeResources"]
        self.assertEqual(compute_resources["Type"], "EC2")
        self.assertNotIn("SpotBidPercentage", compute_resources)

    def test_priority_queue_is_on_demand_with_configured_limits(self) -> None:
        """Create a higher-priority On-Demand queue using its own vCPU bounds."""
        template, _ = self.make_compute_template()
        environments = template.find_resources("AWS::Batch::ComputeEnvironment")
        priority = next(
            resource
            for resource in environments.values()
            if resource["Properties"]["ComputeResources"]["Type"] == "EC2"
        )
        self.assertEqual(priority["Properties"]["ComputeResources"]["MinvCpus"], 0)
        self.assertEqual(priority["Properties"]["ComputeResources"]["MaxvCpus"], 64)
        queues = template.find_resources("AWS::Batch::JobQueue")
        self.assertTrue(
            any(queue["Properties"]["Priority"] == 10 for queue in queues.values())
        )
