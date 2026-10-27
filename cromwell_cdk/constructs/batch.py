"""AWS Batch EC2 launch-template and default compute configuration."""

import shlex

from aws_cdk import aws_batch as batch, aws_ec2 as ec2
from constructs import Construct

from cromwell_cdk.config import DeploymentConfig
from cromwell_cdk.constructs.iam import BatchRoles
from cromwell_cdk.constructs.network import BatchNetwork


class BatchLaunchTemplate(Construct):
    """Create a secure EC2 launch template for AWS Batch compute resources.

    The template deliberately does not select an AMI. AWS Batch owns the
    ``ECS_AL2023`` image selection and update lifecycle, as recorded in research
    decision R8. ECS_AL2023 stores both the operating system and Docker data on
    its root volume, so that single volume is enlarged and encrypted here.

    Args:
        scope: Parent construct.
        construct_id: Stable construct identifier.
        user_data: Optional multipart MIME user data compatible with AWS Batch.
        root_volume_size_gib: Size of the encrypted root/Docker data volume.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        user_data: str | None = None,
        artifact_bucket_name: str | None = None,
        namespace: str | None = None,
        root_volume_size_gib: int = 100,
    ) -> None:
        super().__init__(scope, construct_id)
        if user_data is not None and artifact_bucket_name is not None:
            raise ValueError(
                "Specify custom user_data or artifact_bucket_name, not both"
            )
        if (artifact_bucket_name is None) != (namespace is None):
            raise ValueError(
                "artifact_bucket_name and namespace must be specified together"
            )
        mime_user_data = user_data or (
            self._worker_bootstrap_user_data(artifact_bucket_name, namespace)
            if artifact_bucket_name is not None and namespace is not None
            else self._default_user_data()
        )
        self.launch_template = ec2.LaunchTemplate(
            self,
            "Template",
            require_imdsv2=True,
            http_tokens=ec2.LaunchTemplateHttpTokens.REQUIRED,
            http_endpoint=True,
            http_put_response_hop_limit=1,
            block_devices=[
                ec2.BlockDevice(
                    device_name="/dev/xvda",
                    volume=ec2.BlockDeviceVolume.ebs(
                        root_volume_size_gib,
                        encrypted=True,
                        volume_type=ec2.EbsDeviceVolumeType.GP3,
                        delete_on_termination=True,
                    ),
                ),
            ],
            user_data=ec2.UserData.custom(mime_user_data),
        )

    @staticmethod
    def _default_user_data() -> str:
        """Return a valid empty multipart archive for Batch user-data merging.

        Returns:
            MIME multipart content containing a harmless cloud-config part.
        """
        return (
            "MIME-Version: 1.0\n"
            'Content-Type: multipart/mixed; boundary="==CROMWELL-BATCH=="\n'
            "\n"
            "--==CROMWELL-BATCH==\n"
            'Content-Type: text/cloud-config; charset="us-ascii"\n'
            "\n"
            "#cloud-config\n"
            "\n"
            "--==CROMWELL-BATCH==--\n"
        )

    @staticmethod
    def _worker_bootstrap_user_data(
        artifact_bucket_name: str,
        namespace: str,
    ) -> str:
        """Return multipart user data that installs verified Cromwell worker assets.

        Args:
            artifact_bucket_name: Private bucket containing the staged asset bundle.
            namespace: Deployment namespace used by optional worker integrations.

        Returns:
            MIME multipart content with a shell-script bootstrap part.
        """
        bucket = shlex.quote(artifact_bucket_name)
        deployment_namespace = shlex.quote(namespace)
        script = f"""#!/bin/bash
set -Eeuo pipefail
ASSET_DIR=/opt/cromwell-assets
case "$(uname -m)" in x86_64) AWS_CLI_ARCH=x86_64 ;; aarch64) AWS_CLI_ARCH=aarch64 ;; *) echo 'Unsupported architecture for AWS CLI v2' >&2; exit 1 ;; esac
dnf install -y curl unzip
curl --fail --show-error --silent --location "https://awscli.amazonaws.com/awscli-exe-linux-${{AWS_CLI_ARCH}}.zip" --output /tmp/awscliv2.zip
unzip -q /tmp/awscliv2.zip -d /tmp
/tmp/aws/install --install-dir /usr/local/aws-cli --bin-dir /usr/local/bin
rm -rf /tmp/aws /tmp/awscliv2.zip
AWS=/usr/local/aws-cli/v2/current/bin/aws
install -d -m 0755 "$ASSET_DIR"
"$AWS" s3 cp "s3://{bucket}/assets/" "$ASSET_DIR/" --recursive
"$AWS" s3 cp "s3://{bucket}/assets/CHECKSUMS.sha256" /tmp/cromwell-assets-CHECKSUMS.sha256
cmp --silent /tmp/cromwell-assets-CHECKSUMS.sha256 "$ASSET_DIR/CHECKSUMS.sha256"
cd "$ASSET_DIR"
sha256sum --check CHECKSUMS.sha256
ARTIFACTS_NAMESPACE={deployment_namespace} ASSET_DIRECTORY="$ASSET_DIR" /usr/bin/env bash "$ASSET_DIR/provision.sh"
"""
        return (
            "MIME-Version: 1.0\n"
            'Content-Type: multipart/mixed; boundary="==CROMWELL-BATCH=="\n'
            "\n"
            "--==CROMWELL-BATCH==\n"
            'Content-Type: text/x-shellscript; charset="us-ascii"\n'
            "\n"
            f"{script}"
            "--==CROMWELL-BATCH==--\n"
        )


class DefaultBatchCompute(Construct):
    """Create the default managed EC2 compute environment and Batch queue.

    Args:
        scope: Parent construct.
        construct_id: Stable construct identifier.
        config: Validated deployment configuration.
        network: Batch VPC, security group, and selected private subnets.
        roles: Batch service and instance roles.
        launch_template: Secure launch template for Batch EC2 instances.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: DeploymentConfig,
        network: BatchNetwork,
        roles: BatchRoles,
        launch_template: BatchLaunchTemplate,
    ) -> None:
        super().__init__(scope, construct_id)
        batch_config = config.section("batch")
        spot = batch_config["default_use_spot"]
        compute_environment_props: dict[str, object] = {
            "vpc": network.vpc,
            "vpc_subnets": ec2.SubnetSelection(subnets=network.private_subnets),
            "security_groups": [network.security_group],
            "service_role": roles.service_role,
            "instance_role": roles.instance_role,
            "use_optimal_instance_classes": False,
            "instance_types": [
                ec2.InstanceType(instance_type)
                for instance_type in batch_config["instance_types"]
            ],
            "minv_cpus": batch_config["default_min_vcpus"],
            "maxv_cpus": batch_config["default_max_vcpus"],
            "spot": spot,
            "launch_template": launch_template.launch_template,
            "images": [
                batch.EcsMachineImage(image_type=batch.EcsMachineImageType.ECS_AL2023)
            ],
        }
        if spot:
            compute_environment_props["spot_bid_percentage"] = batch_config[
                "spot_bid_percentage"
            ]
        self.compute_environment = batch.ManagedEc2EcsComputeEnvironment(
            self,
            "DefaultComputeEnvironment",
            **compute_environment_props,
        )
        self.job_queue = batch.JobQueue(
            self,
            "DefaultJobQueue",
            priority=1,
            compute_environments=[
                batch.OrderedComputeEnvironment(
                    compute_environment=self.compute_environment,
                    order=1,
                )
            ],
        )


class PriorityBatchCompute(Construct):
    """Create the On-Demand priority EC2 compute environment and queue.

    Args:
        scope: Parent construct.
        construct_id: Stable construct identifier.
        config: Validated deployment configuration.
        network: Batch VPC, security group, and selected private subnets.
        roles: Batch service and instance roles.
        launch_template: Secure launch template for Batch EC2 instances.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: DeploymentConfig,
        network: BatchNetwork,
        roles: BatchRoles,
        launch_template: BatchLaunchTemplate,
    ) -> None:
        super().__init__(scope, construct_id)
        batch_config = config.section("batch")
        self.compute_environment = batch.ManagedEc2EcsComputeEnvironment(
            self,
            "PriorityComputeEnvironment",
            vpc=network.vpc,
            vpc_subnets=ec2.SubnetSelection(subnets=network.private_subnets),
            security_groups=[network.security_group],
            service_role=roles.service_role,
            instance_role=roles.instance_role,
            use_optimal_instance_classes=False,
            instance_types=[
                ec2.InstanceType(instance_type)
                for instance_type in batch_config["instance_types"]
            ],
            minv_cpus=batch_config["priority_min_vcpus"],
            maxv_cpus=batch_config["priority_max_vcpus"],
            spot=False,
            launch_template=launch_template.launch_template,
            images=[
                batch.EcsMachineImage(image_type=batch.EcsMachineImageType.ECS_AL2023)
            ],
        )
        self.job_queue = batch.JobQueue(
            self,
            "PriorityJobQueue",
            priority=10,
            compute_environments=[
                batch.OrderedComputeEnvironment(
                    compute_environment=self.compute_environment,
                    order=1,
                )
            ],
        )
