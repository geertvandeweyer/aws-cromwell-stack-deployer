# Observability

## Current behavior

`PlatformLogs` defines two CloudWatch Logs groups for the platform:

- `/cromwell/batch/jobs` for AWS Batch job logs.
- `/cromwell/server` for the hosted Cromwell service.

Both groups use `[observability] log_retention_days` from the shared deployment
configuration. The default is 30 days. Log groups use a `RETAIN` removal policy
so deleting the infrastructure stack does not implicitly delete diagnostic
history.

The hosted Cromwell service redirects its server output to
`/var/log/cromwell/server.log`; CloudWatch delivery is configured through the
host's log collection/bootstrap assets. Batch job logs use the job log group
when Batch job definitions configure the `awslogs` driver. Confirm log-stream
creation and workflow/job identifiers in a live deployment. See
[deployment](deployment.md) for deployment lifecycle and
[configuration](configuration.md) for the retention setting.