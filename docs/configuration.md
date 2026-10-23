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
	The default artifact is the official
	[Cromwell 92 release JAR](https://github.com/broadinstitute/cromwell/releases/download/92/cromwell-92.jar),
	SHA-256 `e0e3a050d4124e81369a79059e5774142b2f06bd89df4a0b035f559db85cedf5`.
	`artifact_url` may override it with an HTTPS URL, or `artifact_path` may
	select a local JAR; set exactly one and provide its expected 64-digit
	hexadecimal `sha256`. A checksum without a source override is rejected.
	Source staging and digest verification are provided by
	`cromwell_cdk.artifact_source.stage_cromwell_jar` and the
	`stage-cromwell-artifact` command. CDK synth and private bucket upload do not
	invoke it yet.
- `[database]`: finite ACU values with `max_acu >= min_acu`; a hosted database
	without hosted Cromwell requires `standalone_ok = true`.
- `[additional_s3_buckets]`: declare sequential `bucketN_name` entries with
	optional `bucketN_prefix` and `bucketN_access` (`readonly` by default, or
	`full`). Bucket names, prefixes, modes, gaps, incomplete entries, and a
	conservative inline IAM policy-size budget are validated before synthesis.
	Grants apply to Batch workers; changing the declarations is reconciled by
	the normal stack deployment. Cross-account bucket policies remain the
	bucket owner's responsibility.
- `[mountpoint_s3]`: only `mount1` through `mount5` keys are accepted, and
	each access mode must be `ro` or `rw`.
- `[batch]`: non-negative minimum vCPUs, maximum vCPUs not below minimum, a
	non-empty instance-type list, Spot bid percentage from 1 to 100, and
	`priority_use_spot = false` so the priority queue remains On-Demand; setting
	it to `true` is rejected.
- `[artifacts] verify_checksums` must remain `true`.
- Storage, artifact, database, encryption, FSx type, and CloudWatch retention
	values are restricted to supported enumerations.

External connectivity validation belongs to T033. Destructive-removal
confirmation belongs to the CLI contract (T045). Subnet/AZ lookups, AWS
resource checks are not performed by this configuration loader. Artifact
source settings are validated locally; the staging helper verifies SHA-256
before writing the selected JAR. No AWS resources are created by parsing or
validation.

The current CDK shell does not read configuration and does not deploy AWS
resources.
