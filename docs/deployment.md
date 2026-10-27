# Development and deployment setup

## Current implementation status

The repository contains the Python CDK entry point, the `deploy-cromwell` CLI,
the existing-VPC network foundation, encrypted workflow/artifact buckets,
Batch queues, and optional hosted Cromwell/Aurora resources. The CLI defaults
to the safe `synth` action. Explicit `--action deploy` deploys the stack and
then waits for the default Batch queue to become `VALID`; if Cromwell is hosted,
it also checks `/engine/v1/status`. `--dry-run` always runs synth, even if a
different action was requested.

## Prerequisites

- Python 3.12 or newer.
- Node.js LTS, required by the CDK jsii runtime, and the AWS CDK v2 CLI
  compatible with the pinned `aws-cdk-lib` minor line in `pyproject.toml`.
- An existing AWS VPC with at least two private subnets in distinct Availability
  Zones is required; no VPC is created. Public hosted Cromwell additionally
  requires at least two public subnets.
- An AWS account/profile and region will be needed for deployment. Do not put
  credentials or account-specific secrets in `configuration.ini`.

## Install development dependencies

Create an isolated Python environment and install the project with its declared
development dependencies from `pyproject.toml` (using `uv sync --extra dev` or
`python3.12 -m pip install -e '.[dev]'`). `uv.lock` pins the full resolved
dependency graph for repeatable `uv` installs. Install the repository's Git hooks
with `pre-commit install`.

## CLI validation and synthesis

Install the project, create a local `configuration.ini` from
`configuration.example.ini`, and supply the required AWS region and root bucket:

```text
deploy-cromwell --region eu-west-1 --cromwell-root-bucket my-cromwell-root \
  --config configuration.ini --dry-run
```

`--dry-run` validates local configuration, runs CDK synth without context
lookups, and does not invoke deploy/destroy. The subnet/AZ lookup is therefore
skipped when the VPC is not present in CDK context; synth reports the missing
lookup prerequisite instead of making a live AWS read. To validate against
previously cached context, provide the VPC lookup entry in CDK's standard
`cdk.context.json` file. With cached VPC context, synthesis verifies the
configured subnet membership and distinct AZs without AWS access.
The artifact bucket blocks public access, enforces TLS, uses KMS encryption,
enables versioning, and is retained by default. The staging helper verifies the
configured Cromwell JAR and generates a `CHECKSUMS.sha256` manifest before
placing it in a temporary assets directory. The default is the official
Cromwell 92 release. For local validation, set
`[cromwell] artifact_path` to a local JAR and `sha256` to its independently
calculated digest; alternatively, set an HTTPS `artifact_url` and the expected
`sha256`. Only one override source may be set. A mismatch fails before
replacing the staged artifact. The user's 93-SNAPSHOT test JAR is not included
in the repository or release defaults. Run `stage-cromwell-artifact --config
configuration.ini --output /tmp/cromwell.jar` to stage and verify the configured
JAR explicitly. This helper by itself does not upload the JAR to S3; hosted
deployment packages and uploads the verified JAR plus complete asset manifest.
For local/in-house AWS Batch changes, configure `artifact_path` to a JAR built
from the sibling `cromwell_src` checkout and set `sha256` to that exact JAR's
digest; the official release default does not include checkout-only behavior.
The local-source build currently identifies as Cromwell 93-SNAPSHOT. Shared
filesystem mounts and sized per-task local disks additionally require host
provisioning beyond the current deployer; see [storage.md](storage.md).
The supported actions are `synth` (default), `deploy`, and `destroy`. A
`DESTROY` removal policy requires `--confirm-destroy-data` for any action.
Successful deploy requires AWS credentials with CloudFormation/CDK permissions
and `batch:DescribeJobQueues`; hosted Cromwell readiness also requires network
reachability from the deployment client to its endpoint. Private endpoints
must be checked from within the VPC or through an operator-managed connection.

For AWS Batch workflows, set the `aws_batch_job_role_arn` workflow option to the
stack output `BatchWorkflowJobRoleArn`. The local AWS Batch backend reads this
from each submitted workflow's options; it is not a supported server-wide
configuration default.

Exit codes: `0` success, `2` invalid arguments or missing destructive
confirmation, `3` invalid or missing configuration, `4` missing CDK
prerequisite, and `5` CDK operation failure. Diagnostics are written to stderr
and name the configuration key when applicable. See
[configuration.md](configuration.md) for the supported keys and deterministic
validation rules, [architecture.md](architecture.md) for component/data flow,
[security.md](security.md) for IAM and ingress constraints, and
[observability.md](observability.md) for log retention and collection.

## Post-deploy readiness

After a successful CDK deploy, the CLI reads stack outputs, polls the default
Batch queue until its status is `VALID`, and—when the stack exports
`CromwellEndpoint`—requests `/engine/v1/status`. Each check has a bounded
five-minute retry window. Batch API failures, missing output, invalid queue
status, or Cromwell health timeout are reported as operation failures (exit
code 5) with the failed component named. An internal endpoint cannot be
reached from an operator workstation unless that client has VPC connectivity.

## Cost and teardown

Batch compute, ALB, Aurora Serverless ACUs, S3 storage/requests, KMS keys, and
CloudWatch ingestion/retention contribute to cost. No live account deployment
or destructive teardown has been run from this worktree. Confirm engine
orderability for `db.serverless`, JDBC TLS behavior, subnet routing, IAM,
quotas, and expected costs in a disposable account before production. The
Aurora version is a candidate pin; synthesis alone does not establish regional
availability.


## Artifact bucket

The platform creates a dedicated artifact bucket with S3 Block Public Access,
TLS-only access, KMS encryption, versioning, and a `RETAIN` removal policy by
default. Its name is exposed as the `ArtifactBucketName` stack output. Before
synthesis, the app verifies every checked-in static asset against
`cromwell_cdk/assets/CHECKSUMS.sha256`. For hosted Cromwell, it also stages and
verifies the pinned official Cromwell 92 JAR or configured local/HTTPS override.
CDK packages this temporary assembly and uploads it under the `assets/` prefix;
the deployment does not prune unrelated keys and retains uploaded objects if
the stack is removed. With hosted Cromwell disabled, no JAR path is read and no
release download occurs. No large release JAR is checked into the repository.
