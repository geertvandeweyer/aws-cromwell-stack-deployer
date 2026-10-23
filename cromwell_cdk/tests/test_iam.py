"""Template tests for scoped AWS Batch IAM roles."""

from __future__ import annotations

import aws_cdk as cdk
from aws_cdk import assertions, aws_s3 as s3
from cromwell_cdk.constructs.iam import BatchRoles
from cromwell_cdk.tests.base import TestBase


class BatchRoleTests(TestBase):
    """Verify trust relationships and resource-scoped S3 permissions."""

    @staticmethod
    def _policy_statements(template: assertions.Template) -> list[dict]:
        """Collect inline and attached IAM policy statements from a template."""
        statements = []
        for resource_type in ("AWS::IAM::Role", "AWS::IAM::Policy"):
            for resource in template.find_resources(resource_type).values():
                properties = resource["Properties"]
                if resource_type == "AWS::IAM::Policy":
                    policies = [properties["PolicyDocument"]]
                else:
                    policies = [
                        policy["PolicyDocument"]
                        for policy in properties.get("Policies", [])
                    ]
                for policy in policies:
                    statements.extend(policy.get("Statement", []))
        return statements

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

    def test_additional_bucket_grants_are_prefix_scoped_and_readonly_or_full(
        self,
    ) -> None:
        """Grant requested S3 operations only on each declared bucket and prefix."""
        app = cdk.App()
        stack = cdk.Stack(app, "AdditionalBucketIamTest")
        roles = BatchRoles(
            stack,
            "BatchRoles",
            artifact_bucket=s3.Bucket(stack, "ArtifactBucket"),
            data_bucket=s3.Bucket(stack, "DataBucket"),
            additional_s3_grants={
                "1": {
                    "name": "readonly-inputs",
                    "prefix": "cohort-a/",
                    "access": "readonly",
                },
                "2": {"name": "full-results", "prefix": "", "access": "full"},
            },
        )
        statements = self._policy_statements(assertions.Template.from_stack(stack))
        rendered = str(statements)

        self.assertIn("readonly-inputs/cohort-a/*", rendered)
        self.assertIn("cohort-a/*", rendered)
        self.assertIn("full-results/*", rendered)
        self.assertIn("s3:PutObject", rendered)
        self.assertIn("s3:DeleteObject", rendered)
        self.assertNotIn("s3:PutBucket", rendered)
        self.assertNotIn("s3:DeleteBucket", rendered)
        self.assertNotIn("s3:ListAllMyBuckets", rendered)
        self.assertIsNotNone(roles.instance_role)

        readonly_object_statements = [
            statement
            for statement in statements
            if "readonly-inputs" in str(statement.get("Resource", ""))
            and "cohort-a" in str(statement.get("Resource", ""))
        ]
        self.assertTrue(readonly_object_statements)
        self.assertTrue(
            all(
                not any(
                    action
                    in {"s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload"}
                    for action in (
                        statement["Action"]
                        if isinstance(statement["Action"], list)
                        else [statement["Action"]]
                    )
                )
                for statement in readonly_object_statements
            )
        )
