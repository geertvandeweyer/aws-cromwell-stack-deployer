# Observability

## Current behavior

`PlatformLogs` defines two CloudWatch Logs groups for the platform:

- `/cromwell/batch/jobs` for AWS Batch job logs.
- `/cromwell/server` for the hosted Cromwell service.

Both groups use `[observability] log_retention_days` from the shared deployment
configuration. The default is 30 days. Log groups use a `RETAIN` removal policy
so deleting the infrastructure stack does not implicitly delete diagnostic
history.

This construct provisions log destinations only. Batch job definitions and a
hosted Cromwell host are not yet implemented or wired to these groups, so log
delivery and workflow/job identifiers in log streams are not currently
verified. See [deployment](deployment.md) for the current platform status and
[configuration](configuration.md) for the retention setting.