#!/usr/bin/env python3
"""Synthesize the Cromwell workflow platform CDK application."""

import aws_cdk as cdk
from cromwell_cdk.config import load_config, validate_config
from cromwell_cdk.errors import ConfigError


app = cdk.App()

config_path = app.node.try_get_context("deploymentConfig")
if config_path:
    validate_config(load_config(config_path))

root_bucket = app.node.try_get_context("cromwellRootBucket")
if root_bucket is not None and not str(root_bucket).strip():
    raise ConfigError("Invalid --cromwell-root-bucket: value cannot be empty")

if __name__ == "__main__":
    app.synth()
