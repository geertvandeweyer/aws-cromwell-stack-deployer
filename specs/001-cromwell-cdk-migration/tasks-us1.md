# Phase 3 US1 completion tracker

This tracker records work completed in the combined Phase 3 implementation PR.
Items marked as deployment gates still require live AWS verification before
production use.

## Implemented

- [X] Batch IMDSv2 launch template with encrypted ECS_AL2023 root volume.
- [X] Default Spot and priority On-Demand Batch compute environments/queues.
- [X] Data bucket, Batch/host IAM, log groups, and queue/bucket outputs wired.
- [X] Optional Aurora MySQL Serverless v2, TLS enforcement, generated secret,
      and conditional stack output.
- [X] Conditional hosted Cromwell EC2 host, complete asset verification,
      systemd service, private/internal ALB or allowlisted public TLS ALB.
- [X] Deployment readiness waits for both queues and optional Cromwell
      status endpoint; failures map to exit code 5.
- [X] Default and hosted stack assertions, CLI readiness tests, and US1
      architecture/configuration/security/deployment documentation.

## Remaining live deployment gates

- [ ] Verify Aurora engine `8.0.mysql_aurora.3.12.0` orderability for the
      deployment region and `db.serverless` instance class.
- [ ] Deploy in a disposable AWS account to confirm Aurora TLS/JDBC behavior,
      Cromwell 92 bootstrap/runtime compatibility, Batch job-role behavior,
      ALB routing, SSM connectivity, and log delivery.
- [ ] Confirm client-side reachability to a private Cromwell endpoint; the
      deployment client must be inside or connected to the VPC.
- [ ] If `rotate_secret = true`, implement and verify a safe service restart or
      credential refresh after each Secrets Manager rotation.

## Current scope caveats

- Hosted Cromwell defaults to the default queue. Workflows can select the
      priority queue by setting the backend `queueArn` runtime attribute to the
      exported priority queue ARN.
- Aurora is optional for hosted Cromwell; with Aurora disabled Cromwell uses
      its packaged metadata configuration. Durable metadata requires Aurora.
- Public ALB subnet readiness is validated from VPC lookup context; ensure the
  operator's public subnet routing and internet gateway are configured.
- The CDK synthesis and unit tests do not prove regional service availability
  or successful live AWS deployment.