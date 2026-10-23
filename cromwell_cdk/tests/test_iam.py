"""Template tests for scoped AWS Batch IAM roles."""

from __future__ import annotations

import aws_cdk as cdk
from aws_cdk import assertions, aws_s3 as s3
from cromwell_cdk.constructs.iam import BatchRoles
from cromwell_cdk.tests.base import TestBase


class BatchRoleTests(TestBase):
    """Verify trust relationships and resource-scoped S3 permissions."""

    def test_roles_have_batch_and_ec2_trust_and_scoped_bucket_access(self) -> None:
        """Separate AWS-managed baseline policies from explicit S3 grants."""
        app = cdk.App()
        stack = cdk.Stack(app, "BatchIamTest")
        artifact_bucket = s3.Bucket(stack, "ArtifactBucket")
        data_bucket = s3.Bucket(stack, "DataBucket")
        roles = BatchRoles(
            stack,
            "BatchRoles",
            artifact_bucket=artifact_bucket,
            data_bucket=data_bucket,
        )
        template = assertions.Template.from_stack(stack)

        template.has_resource_properties(
            "AWS::IAM::Role",
            {
                "AssumeRolePolicyDocument": {
                    "Statement": assertions.Match.array_with(
                        [
                            assertions.Match.object_like(
                                {
                                    "Principal": {"Service": "batch.amazonaws.com"},
                                    "Action": "sts:AssumeRole",
                                }
                            )
                        ]
                    )
                }
            },
        )
        template.has_resource_properties(
            "AWS::IAM::Role",
            {
                "AssumeRolePolicyDocument": {
                    "Statement": assertions.Match.array_with(
                        [
                            assertions.Match.object_like(
                                {
                                    "Principal": {"Service": "ec2.amazonaws.com"},
                                    "Action": "sts:AssumeRole",
                                }
                            )
                        ]
                    )
                }
            },
        )
        policies = template.find_resources("AWS::IAM::Policy")
        self.assertTrue(policies)
        serialized_policies = str(policies)
        self.assertIn("s3:GetObject", serialized_policies)
        self.assertIn("assets/*", serialized_policies)
        self.assertIn("s3:PutObject", serialized_policies)
        roles_by_service = template.find_resources("AWS::IAM::Role")
        role_documents = [
            resource["Properties"] for resource in roles_by_service.values()
        ]
        self.assertTrue(
            any(
                "AWSBatchServiceRole" in str(role.get("ManagedPolicyArns", []))
                for role in role_documents
            )
        )
        self.assertTrue(
            any(
                "AmazonEC2ContainerServiceforEC2Role"
                in str(role.get("ManagedPolicyArns", []))
                for role in role_documents
            )
        )
        self.assertIsNotNone(roles.service_role)
        self.assertIsNotNone(roles.instance_role)

    def test_instance_s3_permissions_never_use_wildcard_resource(self) -> None:
        """Constrain every explicit S3 permission to a bucket or object ARN."""
        app = cdk.App()
        stack = cdk.Stack(app, "BatchIamWildcardTest")
        artifact_bucket = s3.Bucket(stack, "ArtifactBucket")
        data_bucket = s3.Bucket(stack, "DataBucket")
        BatchRoles(
            stack,
            "BatchRoles",
            artifact_bucket=artifact_bucket,
            data_bucket=data_bucket,
        )
        template = assertions.Template.from_stack(stack)
        policies = template.find_resources("AWS::IAM::Policy")
        self.assertTrue(policies)
        for policy in policies.values():
            for statement in policy["Properties"]["PolicyDocument"]["Statement"]:
                action = statement.get("Action", [])
                actions = [action] if isinstance(action, str) else action
                if any(str(name).startswith("s3:") for name in actions):
                    resource = statement.get("Resource")
                    resources = [resource] if isinstance(resource, str) else resource
                    self.assertIsNotNone(resources)
                    self.assertNotIn("*", resources)
