# Development and deployment setup

## Current implementation status

The repository contains the Python CDK entry point, the `deploy-cromwell` CLI,
the shared configuration loader, the existing-VPC network foundation, and a
private artifact bucket. The CLI defaults to the safe `synth` action. Explicit `--action deploy` and
`--action destroy` run those operations; do not use them until the platform
resources are implemented. `--dry-run` always runs synth, even if a different
action was requested.

## Prerequisites

- Python 3.12 or newer.
- Node.js LTS, required by the CDK jsii runtime, and the AWS CDK v2 CLI
  compatible with the pinned `aws-cdk-lib` minor line in `pyproject.toml`.
- An existing AWS VPC with at least two private subnets in distinct Availability
  Zones is required for a future platform deployment; no VPC is created.
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
enables versioning, and is retained by default. Repository asset upload and
checksum verification are not implemented yet; do not treat the bucket as
populated until that work is complete.
The supported actions are `synth` (default), `deploy`, and `destroy`; deploy and
destroy remain unavailable for production use until platform infrastructure
exists. A `DESTROY`
removal policy requires `--confirm-destroy-data` for any action.

Exit codes: `0` success, `2` invalid arguments or missing destructive
confirmation, `3` invalid or missing configuration, `4` missing CDK
prerequisite, and `5` CDK operation failure. Diagnostics are written to stderr
and name the configuration key when applicable. See
[configuration.md](configuration.md) for the supported keys and deterministic
validation rules.

## Cost and teardown

The artifact bucket is the current app's only provisioned resource. Batch,
optional storage, database, and compute costs and the final teardown procedure
remain unverified until the corresponding infrastructure tasks and isolated
AWS validation are complete.


## Artifact bucket

The platform creates a dedicated artifact bucket with S3 Block Public Access,
TLS-only access, KMS encryption, versioning, and a `RETAIN` removal policy by
default. Its name is exposed as the `ArtifactBucketName` stack output. The
bucket does not yet contain deployment assets; repository asset packaging,
checksums, and upload are pending review of the legacy scripts and a pinned
Cromwell release artifact. Do not deploy workloads that expect those assets
until that work is completed.
