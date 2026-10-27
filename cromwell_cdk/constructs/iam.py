"""Scoped IAM roles for AWS Batch control and compute resources."""

from __future__ import annotations

from aws_cdk import ArnFormat, Stack, aws_iam as iam, aws_s3 as s3
from constructs import Construct


class BatchRoles(Construct):
    """Create Batch service and EC2 instance roles with scoped bucket access.

    Args:
        scope: Parent construct.
        construct_id: Stable construct identifier.
        artifact_bucket: Private bucket containing repository-owned assets.
        data_bucket: Primary workflow data bucket.
        additional_s3_grants: Validated operator-declared bucket grants.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        artifact_bucket: s3.IBucket,
        data_bucket: s3.IBucket,
        additional_s3_grants: dict[str, dict[str, str]] | None = None,
    ) -> None:
        super().__init__(scope, construct_id)
        self.service_role = iam.Role(
            self,
            "BatchServiceRole",
            assumed_by=iam.ServicePrincipal("batch.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSBatchServiceRole"
                )
            ],
        )
        self.instance_role = iam.Role(
            self,
            "BatchInstanceRole",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AmazonEC2ContainerServiceforEC2Role"
                )
            ],
        )
        self.job_role = iam.Role(
            self,
            "BatchJobRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            description="Scoped credentials for Cromwell AWS Batch workflow containers",
        )
        self.instance_role.add_to_policy(
            iam.PolicyStatement(
                actions=["s3:ListBucket"],
                resources=[artifact_bucket.bucket_arn],
                conditions={"StringLike": {"s3:prefix": ["assets", "assets/*"]}},
            )
        )
        self.instance_role.add_to_policy(
            iam.PolicyStatement(
                actions=["s3:GetObject"],
                resources=[artifact_bucket.arn_for_objects("assets/*")],
            )
        )
        data_bucket.grant_read_write(self.instance_role)
        data_bucket.grant_read_write(self.job_role)
        for grant in (additional_s3_grants or {}).values():
            self._grant_additional_bucket_access(self.instance_role, grant)
            self._grant_additional_bucket_access(self.job_role, grant)

    def _grant_additional_bucket_access(
        self, role: iam.IRole, grant: dict[str, str]
    ) -> None:
        """Grant access to a declared S3 bucket or prefix.

        Args:
            grant: Mapping containing a validated bucket name, prefix, and access mode.
        """
        bucket_arn = Stack.of(self).format_arn(
            service="s3",
            region="",
            account="",
            resource=grant["name"],
        )
        prefix = grant["prefix"]
        list_statement = iam.PolicyStatement(
            actions=["s3:ListBucket"],
            resources=[bucket_arn],
        )
        if prefix:
            list_statement.add_condition(
                "StringLike", {"s3:prefix": [prefix, f"{prefix}*"]}
            )
        role.add_to_policy(list_statement)

        object_actions = ["s3:GetObject"]
        if grant["access"] == "full":
            object_actions.extend(
                [
                    "s3:PutObject",
                    "s3:DeleteObject",
                    "s3:AbortMultipartUpload",
                ]
            )
        object_arn = Stack.of(self).format_arn(
            service="s3",
            region="",
            account="",
            resource=f"{grant['name']}/{prefix}*",
        )
        role.add_to_policy(
            iam.PolicyStatement(actions=object_actions, resources=[object_arn])
        )


class CromwellServerRole(Construct):
    """Create a least-privilege role for the optional Cromwell EC2 host.

    Args:
        scope: Parent construct.
        construct_id: Stable construct identifier.
        data_bucket: Primary workflow bucket used by Cromwell.
        default_queue_arn: Default Batch queue ARN.
        priority_queue_arn: Priority Batch queue ARN.
        database_secret: Optional metadata database secret.
        batch_job_role_arn: ECS task role Cromwell assigns to submitted Batch jobs.
        log_group_arn: Cromwell server log group ARN.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        data_bucket: s3.IBucket,
        default_queue_arn: str,
        priority_queue_arn: str,
        log_group_arn: str,
        batch_job_role_arn: str | None = None,
        artifact_bucket: s3.IBucket | None = None,
        database_secret: object | None = None,
    ) -> None:
        super().__init__(scope, construct_id)
        self.role = iam.Role(
            self,
            "Role",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "AmazonSSMManagedInstanceCore"
                )
            ],
        )
        data_bucket.grant_read_write(self.role)
        if artifact_bucket is not None:
            artifact_bucket.grant_read(self.role)
        self.role.add_to_policy(
            iam.PolicyStatement(
                actions=["batch:SubmitJob"],
                resources=[default_queue_arn, priority_queue_arn],
            )
        )
        self.role.add_to_policy(
            iam.PolicyStatement(
                actions=["batch:SubmitJob"],
                resources=[
                    Stack.of(self).format_arn(
                        service="batch",
                        resource="job-definition",
                        resource_name="*",
                        arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                    )
                ],
            )
        )
        self.role.add_to_policy(
            iam.PolicyStatement(
                actions=["batch:DescribeJobs", "batch:TerminateJob"],
                resources=["*"],
            )
        )
        self.role.add_to_policy(
            iam.PolicyStatement(
                actions=["batch:DescribeJobDefinitions", "batch:RegisterJobDefinition"],
                resources=["*"],
                conditions={"StringLike": {"batch:JobDefinitionName": "cromwell_*"}},
            )
        )
        self.role.add_to_policy(
            iam.PolicyStatement(
                actions=["batch:DescribeJobQueues"],
                resources=[default_queue_arn, priority_queue_arn],
            )
        )
        self.role.add_to_policy(
            iam.PolicyStatement(
                actions=["batch:ListJobs"],
                resources=["*"],
            )
        )
        if batch_job_role_arn is not None:
            self.role.add_to_policy(
                iam.PolicyStatement(
                    actions=["iam:PassRole"],
                    resources=[batch_job_role_arn],
                    conditions={
                        "StringEquals": {
                            "iam:PassedToService": "ecs-tasks.amazonaws.com"
                        }
                    },
                )
            )
        if database_secret is not None:
            database_secret.grant_read(self.role)
        self.role.add_to_policy(
            iam.PolicyStatement(
                actions=["logs:CreateLogStream", "logs:PutLogEvents"],
                resources=[f"{log_group_arn}:*"],
            )
        )
