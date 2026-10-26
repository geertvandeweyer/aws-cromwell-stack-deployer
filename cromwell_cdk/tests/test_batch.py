"""Synthesis tests for secure Batch launch-template defaults."""

from __future__ import annotations

import aws_cdk as cdk
from aws_cdk import assertions
from cromwell_cdk.constructs.batch import BatchLaunchTemplate
from cromwell_cdk.tests.base import TestBase


class BatchLaunchTemplateTests(TestBase):
    """Verify AMI-neutral, encrypted, IMDSv2 launch-template settings."""

    def test_template_encrypts_shared_root_and_docker_volume(self) -> None:
        """Synthesize secure metadata and the shared AL2023 data volume."""
        app = cdk.App()
        stack = cdk.Stack(app, "BatchLaunchTemplateTest")
        batch_template = BatchLaunchTemplate(stack, "BatchLaunchTemplate")
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
