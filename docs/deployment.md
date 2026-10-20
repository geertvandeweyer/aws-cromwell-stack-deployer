# Development and deployment setup

## Current implementation status

The repository contains the Python CDK entry point and empty application shell.
The deployment CLI, platform stack, and AWS resources are not implemented yet;
commands below validate the CDK shell only and do not deploy infrastructure.

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

## Synthesize the current empty CDK app

Run `cdk synth` from the repository root. This invokes `python app.py`; at this
stage it synthesizes an empty CDK app, not a Cromwell platform stack. The
`deploy-cromwell` CLI and its dry-run behavior will be documented here when
implemented and validated.

## Cost and teardown

No AWS resources are provisioned by the current empty app. Batch, S3, optional
storage, database, and compute costs and the final teardown procedure remain
unverified until the corresponding infrastructure tasks and isolated AWS
validation are complete.
