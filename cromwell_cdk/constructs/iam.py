"""Scoped IAM roles for AWS Batch control and compute resources."""

from __future__ import annotations

from aws_cdk import aws_iam as iam, aws_s3 as s3
from constructs import Construct


class BatchRoles(Construct):
    """Create Batch service and EC2 instance roles with scoped bucket access.

    Args:
        scope: Parent construct.
        construct_id: Stable construct identifier.
        artifact_bucket: Private bucket containing repository-owned assets.
        data_bucket: Primary workflow data bucket.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        artifact_bucket: s3.IBucket,
        data_bucket: s3.IBucket,
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
