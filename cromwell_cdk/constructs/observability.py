"""CloudWatch log groups for Batch and hosted Cromwell workloads."""

from __future__ import annotations

from aws_cdk import RemovalPolicy, aws_logs as logs
from constructs import Construct

from cromwell_cdk.config import DeploymentConfig

_RETENTION_DAYS = {
    1: logs.RetentionDays.ONE_DAY,
    3: logs.RetentionDays.THREE_DAYS,
    5: logs.RetentionDays.FIVE_DAYS,
    7: logs.RetentionDays.ONE_WEEK,
    14: logs.RetentionDays.TWO_WEEKS,
    30: logs.RetentionDays.ONE_MONTH,
    60: logs.RetentionDays.TWO_MONTHS,
    90: logs.RetentionDays.THREE_MONTHS,
    120: logs.RetentionDays.FOUR_MONTHS,
    150: logs.RetentionDays.FIVE_MONTHS,
    180: logs.RetentionDays.SIX_MONTHS,
    365: logs.RetentionDays.ONE_YEAR,
    400: logs.RetentionDays.THIRTEEN_MONTHS,
    545: logs.RetentionDays.EIGHTEEN_MONTHS,
    731: logs.RetentionDays.TWO_YEARS,
    1827: logs.RetentionDays.FIVE_YEARS,
    3653: logs.RetentionDays.TEN_YEARS,
}


class PlatformLogs(Construct):
    """Create retained log groups with the configured retention period.

    Args:
        scope: Parent construct.
        construct_id: Stable construct identifier.
        config: Validated deployment configuration.
    """

    def __init__(
        self, scope: Construct, construct_id: str, config: DeploymentConfig
    ) -> None:
        super().__init__(scope, construct_id)
        retention_days = config.get("observability", "log_retention_days")
        retention = _RETENTION_DAYS[retention_days]
        self.batch_jobs = logs.LogGroup(
            self,
            "BatchJobs",
            log_group_name="/cromwell/batch/jobs",
            retention=retention,
            removal_policy=RemovalPolicy.RETAIN,
        )
        self.cromwell_server = logs.LogGroup(
            self,
            "CromwellServer",
            log_group_name="/cromwell/server",
            retention=retention,
            removal_policy=RemovalPolicy.RETAIN,
        )
