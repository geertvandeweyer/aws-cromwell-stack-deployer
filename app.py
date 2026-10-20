#!/usr/bin/env python3
"""Synthesize the Cromwell workflow platform CDK application."""

import aws_cdk as cdk


app = cdk.App()

if __name__ == "__main__":
    app.synth()
