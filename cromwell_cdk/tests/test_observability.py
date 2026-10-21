"""Template tests for platform log-group retention."""

from __future__ import annotations

from pathlib import Path

import aws_cdk as cdk
from aws_cdk import assertions

from cromwell_cdk.config import load_config
from cromwell_cdk.constructs.observability import PlatformLogs
from cromwell_cdk.tests.base import TestBase


class PlatformLogsTests(TestBase):
    """Verify the platform log groups use configured retention."""

    def setUp(self) -> None:
        """Load the shared valid deployment configuration fixture."""
        super().setUp()
        config_path = Path(__file__).parents[2] / "configuration.example.ini"
        self.config_path = Path(self.temp_dir) / "configuration.ini"
        self.config_path.write_text(config_path.read_text())
        self.config = load_config(self.config_path)

    def make_template(self) -> assertions.Template:
        """Synthesize standalone platform log groups.

        Returns:
            CloudFormation template assertions wrapper.
        """
        app = cdk.App()
        stack = cdk.Stack(app, "ObservabilityTestStack")
        PlatformLogs(stack, "Logs", self.config)
        return assertions.Template.from_stack(stack)

    def test_batch_and_cromwell_logs_use_configured_retention(self) -> None:
        """Create both log groups with the configured 30-day retention."""
        template = self.make_template()
        template.resource_count_is("AWS::Logs::LogGroup", 2)
        template.has_resource_properties(
            "AWS::Logs::LogGroup",
            {
                "LogGroupName": "/cromwell/batch/jobs",
                "RetentionInDays": 30,
            },
        )
        template.has_resource_properties(
            "AWS::Logs::LogGroup",
            {
                "LogGroupName": "/cromwell/server",
                "RetentionInDays": 30,
            },
        )
        template.all_resources_properties(
            "AWS::Logs::LogGroup", {"RetentionInDays": 30}
        )
        template.all_resources("AWS::Logs::LogGroup", {"DeletionPolicy": "Retain"})

    def test_configured_log_retention_is_applied(self) -> None:
        """Use the operator's configured retention on each log group."""
        text = self.config_path.read_text().replace(
            "log_retention_days = 30", "log_retention_days = 90", 1
        )
        self.config_path.write_text(text)
        self.config = load_config(self.config_path)
        template = self.make_template()
        template.all_resources_properties(
            "AWS::Logs::LogGroup", {"RetentionInDays": 90}
        )
