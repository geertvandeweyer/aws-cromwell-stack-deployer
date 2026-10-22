#!/usr/bin/env python3
"""Synthesize the Cromwell workflow platform CDK application."""

import os
from tempfile import TemporaryDirectory

import aws_cdk as cdk
from cromwell_cdk.artifact_assets import prepare_artifact_assets
from cromwell_cdk.config import load_config, validate_config
from cromwell_cdk.errors import ConfigError, PrereqError


app = cdk.App()
artifact_assets_temp = None

config_path = app.node.try_get_context("deploymentConfig")
if config_path:
    config = load_config(config_path)
    validate_config(config)
    account = os.environ.get("CDK_DEFAULT_ACCOUNT")
    region = os.environ.get("CDK_DEFAULT_REGION")
    if not account:
        raise PrereqError(
            "Required prerequisite missing: AWS account could not be resolved for the VPC lookup"
        )
    if not region:
        raise ConfigError("Missing required deployment region for the VPC lookup")
    from cromwell_cdk.stacks.platform_stack import PlatformStack

    artifact_assets_temp = TemporaryDirectory(prefix="cromwell-cdk-assets-")
    artifact_assets_path = prepare_artifact_assets(config, artifact_assets_temp.name)

    PlatformStack(
        app,
        "CromwellPlatform",
        config=config,
        env={"account": account, "region": region},
        artifact_assets_path=str(artifact_assets_path),
    )

root_bucket = app.node.try_get_context("cromwellRootBucket")
if root_bucket is not None and not str(root_bucket).strip():
    raise ConfigError("Invalid --cromwell-root-bucket: value cannot be empty")

if __name__ == "__main__":
    app.synth()
