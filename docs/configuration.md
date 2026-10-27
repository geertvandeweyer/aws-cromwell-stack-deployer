# Configuration reference

The configuration contract is `configuration.ini`, loaded by the shared
`cromwell_cdk.config` module. The non-secret starting template is
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
	least two distinct subnet IDs. VPC existence, configured subnet membership,
	and distinct Availability Zones are checked during stack synthesis using
	VPC lookup context.
- `[access] public_access`: requires hosted Cromwell, a non-empty restricted
	CIDR allowlist, and a TLS certificate ARN. Unrestricted IPv4/IPv6 CIDRs are
	rejected. Public mode requires at least two public VPC subnets and configures
	an internet-facing ALB with HTTPS/443. The default private mode uses an
	internal ALB with HTTP/80, reachable within the VPC.
- `[cromwell] hosted`: requires a pinned, non-empty version (not `latest`).
	The default artifact is the official
	[Cromwell 92 release JAR](https://github.com/broadinstitute/cromwell/releases/download/92/cromwell-92.jar),
	SHA-256 `e0e3a050d4124e81369a79059e5774142b2f06bd89df4a0b035f559db85cedf5`.
	`artifact_url` may override it with an HTTPS URL, or `artifact_path` may
	select a local JAR; set exactly one and provide its expected 64-digit
	hexadecimal `sha256`. A checksum without a source override is rejected.
	Source staging and digest verification are provided by
	`cromwell_cdk.artifact_source.stage_cromwell_jar` and the
	`stage-cromwell-artifact` command. Hosted deployment stages the verified JAR
	and complete asset manifest to the private artifact bucket.
- `[database] hosted`: creates Aurora MySQL Serverless v2 only when true. The
	required `engine_version` is pinned to candidate version
	`8.0.mysql_aurora.3.12.0`; regional orderability remains unverified and must
	be confirmed before deployment. ACU values must be finite and
	`max_acu >= min_acu`. A hosted database without hosted Cromwell requires
	`standalone_ok = true`.
- `[database] rotate_secret`: defaults to `false`. When enabled, a
	single-user Secrets Manager rotation is scheduled every 30 days. Cromwell
	loads database credentials at service startup, so operators must restart or
	refresh the Cromwell service after rotation.
- When hosted Cromwell is enabled without Aurora, Cromwell uses its packaged
	default metadata configuration. Enable `[database] hosted = true` for
	persistent Aurora-backed metadata.
- `[database] rotate_secret`: defaults to `false`. If enabled, a Secrets
	Manager single-user rotation is scheduled every 30 days. Cromwell reads the
	password at startup and does not refresh its live JDBC pool, so operators
	must restart/refresh Cromwell after rotation.
- `[additional_s3_buckets]`: declare sequential `bucketN_name` entries with
	optional `bucketN_prefix` and `bucketN_access` (`readonly` by default, or
	`full`). Bucket names, prefixes, modes, gaps, incomplete entries, and a
	conservative inline IAM policy-size budget are validated before synthesis.
	Grants apply to Batch workers; changing the declarations is reconciled by
	the normal stack deployment. Cross-account bucket policies remain the
	bucket owner's responsibility.
- `[mountpoint_s3]`: only `mount1` through `mount5` keys are accepted, and
	each access mode must be `ro` or `rw`. Mountpoint setup is not supported by
	this US1 deployment; the current Batch worker bootstrap skips it.
- `[batch]`: non-negative minimum vCPUs, maximum vCPUs not below minimum, a
	non-empty instance-type list, Spot bid percentage from 1 to 100, and
	`priority_use_spot = false` so the priority queue remains On-Demand; setting
	it to `true` is rejected.
- `[artifacts] verify_checksums` must remain `true`.
- Storage, artifact, database, encryption, FSx type, and CloudWatch retention
	values are restricted to supported enumerations.

External-hosted Cromwell uses AWS service APIs and does not require callback
ports or source CIDRs to Batch instances. Destructive-removal confirmation is
handled by the CLI contract. Artifact source settings are validated locally;
the staging helper verifies SHA-256 before packaging. Parsing is local-only;
stack synthesis/deployment performs AWS-aware VPC and resource validation.
See [architecture](architecture.md) for the deployment topology and
[deployment](deployment.md) for the CLI lifecycle.
