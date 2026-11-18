# Architecture

## Platform topology

The CDK stack creates a dedicated VPC with public and private subnets in the
configured Availability Zones. The default network provisions one shared NAT
gateway for private-subnet egress and an S3 gateway endpoint. A shared NAT
reduces fixed cost relative to one NAT per AZ, with a cross-AZ egress dependency
and possible cross-AZ data charges. The default stack provisions:

- A private, versioned, KMS-encrypted artifact bucket for reviewed bootstrap
  assets.
- A primary workflow S3 bucket with public access blocked, TLS required,
  versioning, and configured retention.
- A VPC, subnet routing, and a Batch security group.
- A Batch service role and an EC2 instance role with access to the artifact,
  workflow, and explicitly configured additional S3 buckets.
- A shared Batch launch template requiring IMDSv2 and encrypting the
  ECS_AL2023 root volume.
- A default Spot compute environment/queue and a priority On-Demand compute
  environment/queue, both in the selected private subnets.
- Retained CloudWatch log groups for Batch jobs and the optional Cromwell
  service.

## Optional hosted services

`[cromwell] hosted = true` adds a private EC2 host in a selected private
subnet. It downloads the complete verified asset set from the private artifact
bucket, configures a systemd-managed Cromwell 92 process, and serves Cromwell
through an Application Load Balancer. With `public_access = false`, the ALB is
internal and listens on HTTP/80 inside the VPC. With public access enabled,
the ALB uses HTTPS/443, an ACM certificate, and only the configured
`allowed_cidrs`. Public mode requires at least two public VPC subnets; public
listener TLS terminates at the ALB.

`[database] hosted = true` adds a private Aurora MySQL Serverless v2 cluster,
encrypted storage, TLS enforcement, a generated Secrets Manager secret, and a
database security group that accepts MySQL only from the hosted Cromwell host.
Its engine pin is `8.0.mysql_aurora.3.12.0`. Confirm regional orderability
before deployment. Secret rotation is disabled by default because Cromwell's
JDBC pool does not refresh rotated credentials automatically. Setting
`rotate_secret = true` enables 30-day rotation and requires an operator-managed
restart/refresh procedure.

A hosted database without a hosted Cromwell host is rejected unless
`standalone_ok = true` is explicitly set. If Cromwell is hosted without Aurora,
the packaged Cromwell configuration supplies its default metadata behavior;
use Aurora when durable metadata is required.

The VPC CIDR defaults to `10.0.0.0/16` and is configurable to avoid overlap
with networks that may later connect. `availability_zones` defaults to `3`; set
it to `2` or `max` to use all AZs available to the deploying account. The
deployment requires at least two AZs. Flow logs are disabled by default. EFS
remains an existing optional setting, but this stack does not provision EFS
resources. Network and platform resources share one stack lifecycle, so
deleting the stack deletes the VPC and its network resources.

## Workflow data flow

1. A user submits a workflow to Cromwell, either through the hosted ALB or an
   operator-hosted Cromwell installation.
2. Cromwell uses AWS service APIs to submit and monitor Batch jobs using the
   default or priority queue, and uses the primary S3 bucket for workflow and
   execution data.
3. Batch EC2 workers pull staged runtime assets and access the workflow data
   bucket according to their instance role. Additional bucket grants are
   separately configured and prefix-scoped.
4. If enabled, Cromwell reads metadata database credentials from Secrets
   Manager at startup and connects over TLS to the private Aurora endpoint.
5. Batch and Cromwell logs are delivered to the configured CloudWatch log
   groups.

No external-source ingress is added to Batch compute instances. Operator-hosted
Cromwell needs network egress and AWS credentials/IAM permissions for Batch,
S3, and any other configured AWS APIs; see [security](security.md).