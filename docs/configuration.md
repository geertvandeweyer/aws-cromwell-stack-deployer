# Configuration reference

The intended configuration contract is `configuration.ini`, loaded by the
future shared `cromwell_cdk.config` module. The non-secret starting template is
[`configuration.example.ini`](../configuration.example.ini). Do not commit a
local `configuration.ini` or place credentials in it.

The shared loader and deterministic validation are implemented in
`cromwell_cdk.config`. Required sections are enforced, unknown sections and
keys are rejected, scalar values are parsed using the documented example's
types, and diagnostics name the offending section/key. Defaults are applied
for omitted keys.

Current deterministic validation covers:

- `[deployment] namespace`: 1–32 lowercase letters, digits, or hyphens.
- `[network] vpc_id` and `private_subnet_ids`: valid-looking AWS IDs and at
	least two distinct subnet IDs. VPC existence and distinct Availability
	Zones require AWS-aware validation and are not checked by this local loader.
- `[access] public_access`: requires hosted Cromwell, a non-empty restricted
	CIDR allowlist, and a TLS certificate ARN. Unrestricted IPv4/IPv6 CIDRs are
	rejected.
- `[cromwell] hosted`: requires a pinned, non-empty version (not `latest`).
- `[database]`: finite ACU values with `max_acu >= min_acu`; a hosted database
	without hosted Cromwell requires `standalone_ok = true`.
- `[mountpoint_s3]`: only `mount1` through `mount5` keys are accepted, and
	each access mode must be `ro` or `rw`.
- `[batch]`: non-negative minimum vCPUs, maximum vCPUs not below minimum, a
	non-empty instance-type list, and Spot bid percentage from 1 to 100.
- `[artifacts] verify_checksums` must remain `true`.
- Storage, artifact, database, encryption, FSx type, and CloudWatch retention
	values are restricted to supported enumerations.

External connectivity validation belongs to T033. Destructive-removal
confirmation belongs to the CLI contract (T045). Subnet/AZ lookups, AWS
resource checks, and artifact-source validation are not performed by this
configuration loader. No AWS resources are created by parsing or validation.

The current CDK shell does not read configuration and does not deploy AWS
resources.
