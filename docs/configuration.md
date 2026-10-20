# Configuration reference

The intended configuration contract is `configuration.ini`, loaded by the
future shared `cromwell_cdk.config` module. The non-secret starting template is
[`configuration.example.ini`](../configuration.example.ini). Do not commit a
local `configuration.ini` or place credentials in it.

Configuration loading and deployment are not implemented yet. The example file
lists the planned sections and sample keys; defaults and validation behavior
will be documented here as they are implemented and verified.

The current CDK shell does not read configuration and does not deploy AWS
resources.
