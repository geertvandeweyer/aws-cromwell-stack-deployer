# Development and deployment setup

## Current implementation status

The repository contains the Python CDK entry point and empty application shell,
the `deploy-cromwell` CLI, and the shared configuration loader. The platform
stack and AWS resources are not implemented yet. The CLI defaults to the safe
`synth` action, but CDK reports an empty application as a failed synth (exit 5).
Explicit `--action deploy` and `--action destroy` run those operations; do not use them
until the platform stack is implemented. `--dry-run` always runs synth, even if
a different action was requested.

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

`--dry-run` validates configuration, runs CDK synth without context lookups, and
does not invoke deploy/destroy. AWS-aware checks are reported as not implemented
yet; this command cannot succeed until at least one CDK stack is implemented.
The supported actions are `synth` (default), `deploy`, and `destroy`; deploy and destroy remain
unavailable for production use until infrastructure stacks exist. A `DESTROY`
removal policy requires `--confirm-destroy-data` for any action.

Exit codes: `0` success, `2` invalid arguments or missing destructive
confirmation, `3` invalid or missing configuration, `4` missing CDK
prerequisite, and `5` CDK operation failure. Diagnostics are written to stderr
and name the configuration key when applicable. See
[configuration.md](configuration.md) for the supported keys and deterministic
validation rules.

## Cost and teardown

No AWS resources are provisioned by the current empty app. Batch, S3, optional
storage, database, and compute costs and the final teardown procedure remain
unverified until the corresponding infrastructure tasks and isolated AWS
validation are complete.
