"""Optional private Cromwell EC2 host and load-balanced endpoint."""

from __future__ import annotations

import ipaddress
import shlex

from aws_cdk import (
    Duration,
    Stack,
    aws_batch as batch,
    aws_ec2 as ec2,
    aws_elasticloadbalancingv2 as elbv2,
    aws_elasticloadbalancingv2_targets as elbv2_targets,
    aws_iam as iam,
    aws_logs as logs,
    aws_s3 as s3,
)
from constructs import Construct

from cromwell_cdk.config import DeploymentConfig
from cromwell_cdk.constructs.database import MetadataDatabase
from cromwell_cdk.constructs.iam import CromwellServerRole
from cromwell_cdk.constructs.network import BatchNetwork
from cromwell_cdk.errors import PrereqError


class CromwellHost(Construct):
    """Create the hosted Cromwell instance, restricted endpoint, and IAM role.

    Args:
        scope: Parent construct.
        construct_id: Stable construct identifier.
        config: Validated deployment configuration.
        network: Existing VPC and configured private subnet IDs.
        role: Least-privilege Cromwell host role.
        database: Optional cluster with connection endpoint and secret.
        artifact_bucket: Bucket containing checksum-verified deployment assets.
        server_log_group: Retained Cromwell server log group.
        default_queue: Default AWS Batch job queue.
        priority_queue: Priority AWS Batch job queue.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: DeploymentConfig,
        network: BatchNetwork,
        role: CromwellServerRole,
        database: MetadataDatabase | None,
        artifact_bucket: s3.IBucket,
        data_bucket: s3.IBucket,
        server_log_group: logs.ILogGroup,
        default_queue: batch.IJobQueue,
        priority_queue: batch.IJobQueue,
    ) -> None:
        super().__init__(scope, construct_id)
        cromwell_config = config.section("cromwell")
        access = config.section("access")
        self.security_group = ec2.SecurityGroup(
            self,
            "SecurityGroup",
            vpc=network.vpc,
            description="Cromwell application host security group",
            allow_all_outbound=True,
        )
        role.role.add_to_policy(
            iam.PolicyStatement(
                actions=["ssm:UpdateInstanceInformation"],
                resources=["*"],
            )
        )
        server_log_group.grant_write(role.role)
        if database is not None:
            database.security_group.add_ingress_rule(
                self.security_group,
                ec2.Port.tcp(3306),
                "MySQL from Cromwell host",
            )

        self.instance = ec2.Instance(
            self,
            "Instance",
            vpc=network.vpc,
            vpc_subnets=ec2.SubnetSelection(subnets=network.private_subnets),
            security_group=self.security_group,
            instance_type=ec2.InstanceType(cromwell_config["instance_type"]),
            machine_image=ec2.MachineImage.latest_amazon_linux2023(),
            role=role.role,
            require_imdsv2=True,
            detailed_monitoring=True,
        )
        artifact_bucket.grant_read(role.role)
        data_bucket.grant_read_write(role.role)
        self.instance.user_data.add_commands(
            "set -Eeuo pipefail",
            "dnf install -y curl unzip java-17-amazon-corretto-headless python3 amazon-cloudwatch-agent",
            "case \"$(uname -m)\" in x86_64) AWS_CLI_ARCH=x86_64 ;; aarch64) AWS_CLI_ARCH=aarch64 ;; *) echo 'Unsupported architecture for AWS CLI v2' >&2; exit 1 ;; esac",
            "curl --fail --show-error --silent --location "
            '"https://awscli.amazonaws.com/awscli-exe-linux-${AWS_CLI_ARCH}.zip" '
            "--output /tmp/awscliv2.zip",
            "unzip -q /tmp/awscliv2.zip -d /tmp",
            "/tmp/aws/install --install-dir /usr/local/aws-cli --bin-dir /usr/local/bin",
            "rm -rf /tmp/aws /tmp/awscliv2.zip",
            "install -d -o ec2-user -g ec2-user /opt/cromwell /opt/cromwell/assets /var/log/cromwell",
            "aws s3 cp "
            + f"s3://{artifact_bucket.bucket_name}/assets/ "
            + "/opt/cromwell/assets/ --recursive",
            "install -o root -g root -m 0755 "
            "/opt/cromwell/assets/cromwell-entrypoint.sh "
            "/usr/local/bin/cromwell-entrypoint",
            "cd /opt/cromwell/assets",
            "aws s3 cp "
            + f"s3://{artifact_bucket.bucket_name}/assets/CHECKSUMS.sha256 "
            + "/tmp/CHECKSUMS.sha256",
            "cmp --silent /tmp/CHECKSUMS.sha256 CHECKSUMS.sha256",
            "sha256sum --check CHECKSUMS.sha256",
            "install -o ec2-user -g ec2-user -m 0644 /opt/cromwell/assets/cromwell.jar /opt/cromwell/cromwell.jar",
            "cat > /etc/sysconfig/cromwell <<'CROMWELL_ENV'\n"
            + "\n".join(
                [
                    f"CROMWELL_ROOT_BUCKET={self._shell_value(str(data_bucket.bucket_name))}",
                    f"CROMWELL_SCRIPT_BUCKET={self._shell_value(str(data_bucket.bucket_name))}",
                    f"CROMWELL_DEFAULT_QUEUE_ARN={self._shell_value(default_queue.job_queue_arn)}",
                    f"CROMWELL_PRIORITY_QUEUE_ARN={self._shell_value(priority_queue.job_queue_arn)}",
                    f"CROMWELL_DB_HOST={self._shell_value(database.cluster.cluster_endpoint.hostname if database else '')}",
                    f"CROMWELL_DB_SECRET_ARN={self._shell_value(database.secret.secret_arn if database and database.secret else '')}",
                    f"AWS_REGION={self._shell_value(Stack.of(self).region)}",
                ]
            )
            + "\nCROMWELL_ENV",
            "cat > /etc/systemd/system/cromwell.service <<'CROMWELL_UNIT'\n"
            "[Unit]\nDescription=Cromwell workflow engine\nAfter=network-online.target\nWants=network-online.target\n\n"
            "[Service]\nType=simple\nUser=ec2-user\nGroup=ec2-user\n"
            "EnvironmentFile=/etc/sysconfig/cromwell\n"
            "ExecStart=/usr/local/bin/cromwell-entrypoint\n"
            "Restart=on-failure\nRestartSec=10\n\n"
            "[Install]\nWantedBy=multi-user.target\nCROMWELL_UNIT",
            "install -d -m 0755 /opt/aws/amazon-cloudwatch-agent/etc",
            "cat > /opt/aws/amazon-cloudwatch-agent/etc/cromwell.json <<'CW_AGENT'\n"
            "{\n"
            '  "logs": {\n'
            '    "logs_collected": {\n'
            '      "files": {\n'
            '        "collect_list": [{\n'
            '          "file_path": "/var/log/cromwell/server.log",\n'
            '          "log_group_name": "/cromwell/server",\n'
            '          "log_stream_name": "{instance_id}",\n'
            '          "timezone": "UTC"\n'
            "        }]\n"
            "      }\n"
            "    }\n"
            "  }\n"
            "}\nCW_AGENT",
            "/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl "
            "-a fetch-config -m ec2 -c file:/opt/aws/amazon-cloudwatch-agent/etc/cromwell.json -s",
            "chown -R ec2-user:ec2-user /opt/cromwell /var/log/cromwell",
            "systemctl daemon-reload",
            "systemctl enable --now cromwell.service",
        )
        self.target_group = elbv2.ApplicationTargetGroup(
            self,
            "TargetGroup",
            vpc=network.vpc,
            port=8000,
            protocol=elbv2.ApplicationProtocol.HTTP,
            targets=[elbv2_targets.InstanceTarget(self.instance)],
            health_check=elbv2.HealthCheck(
                path="/engine/v1/status",
                healthy_http_codes="200",
                interval=Duration.seconds(30),
                timeout=Duration.seconds(10),
                healthy_threshold_count=2,
                unhealthy_threshold_count=3,
            ),
        )
        public_access = access["public_access"]
        public_subnets = network.vpc.public_subnets
        if public_access and (
            len(public_subnets) < 2
            or len({subnet.availability_zone for subnet in public_subnets}) < 2
        ):
            raise PrereqError(
                "Public Cromwell access requires at least two public VPC subnets "
                "in distinct Availability Zones for the internet-facing load balancer"
            )
        self.load_balancer_security_group = ec2.SecurityGroup(
            self,
            "LoadBalancerSecurityGroup",
            vpc=network.vpc,
            description="Cromwell application load balancer security group",
            allow_all_outbound=True,
        )
        self.load_balancer = elbv2.ApplicationLoadBalancer(
            self,
            "LoadBalancer",
            vpc=network.vpc,
            internet_facing=public_access,
            security_group=self.load_balancer_security_group,
            vpc_subnets=(
                ec2.SubnetSelection(subnets=public_subnets)
                if public_access
                else ec2.SubnetSelection(subnets=network.private_subnets)
            ),
        )
        self.security_group.add_ingress_rule(
            self.load_balancer_security_group,
            ec2.Port.tcp(8000),
            "Cromwell traffic from application load balancer",
        )
        self.listener = self.load_balancer.add_listener(
            "ApplicationListener",
            port=443 if public_access else 80,
            protocol=(
                elbv2.ApplicationProtocol.HTTPS
                if public_access
                else elbv2.ApplicationProtocol.HTTP
            ),
            certificates=[
                elbv2.ListenerCertificate.from_arn(
                    cromwell_config["tls_certificate_arn"]
                )
            ]
            if public_access
            else [],
            open=False,
        )
        self.listener.add_target_groups(
            "CromwellTargets", target_groups=[self.target_group]
        )
        if public_access:
            for cidr in access["allowed_cidrs"]:
                self.load_balancer_security_group.add_ingress_rule(
                    (
                        ec2.Peer.ipv6(cidr)
                        if ipaddress.ip_network(cidr).version == 6
                        else ec2.Peer.ipv4(cidr)
                    ),
                    ec2.Port.tcp(443),
                    "HTTPS allowlist",
                )
        else:
            self.load_balancer_security_group.add_ingress_rule(
                ec2.Peer.ipv4(network.vpc.vpc_cidr_block),
                ec2.Port.tcp(80),
                "Private VPC HTTP access",
            )

    @staticmethod
    def _shell_value(value: str) -> str:
        """Escape a CloudFormation string for a quoted shell environment value."""
        return shlex.quote(value)
