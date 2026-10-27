# Storage

## Cromwell AWS Batch local disks

The local Cromwell AWS backend defaults tasks to `disks = "local-disk"` at
`/cromwell_root`. With the current deployer this uses free space on the
encrypted Batch host root EBS volume; it is not a dedicated per-task volume.
The `disks` attribute accepts an explicit size in the checked-out Cromwell
source, but this deployment does **not** provision the required
`/usr/local/cromwell-disk-utils` host bundle or the EC2 volume lifecycle IAM
permissions. Do not request sized `local-disk` or other sized EBS disks until
that utility, permissions, and an integration test are added.

The local Cromwell checkout also supports shared local mounts and
`filesystems.local.root_locally_available`; these require the mount to exist at
the same absolute path on the Cromwell server and every Batch host. The current
host bootstrap does not create those server-side mounts. Although there are
Mountpoint-related settings and assets in the deployer, they are not yet wired
as Cromwell backend mount configuration and should not be treated as enabled
or supported. A Mountpoint mount requires coherent host provisioning, S3-prefix
configuration, worker/server IAM, and validation against the local Cromwell
backend.

## Primary workflow data bucket

`cromwell_cdk.constructs.storage.DataBucket` creates a primary S3 bucket for
workflow inputs and outputs. The construct requires the bucket name supplied
through the deployment interface and honors `[storage] encryption` and
`[storage] removal_policy`.

Created buckets block all public access, require TLS, enable versioning, and
default to AWS-managed KMS encryption with `RETAIN` on stack deletion. Operators
may select S3-managed encryption (`SSE_S3`) or `DESTROY` explicitly. An S3
bucket name must be globally unique; AWS validates the name and availability
during deployment.

Setting `[storage] existing_bucket = true` imports the supplied primary bucket
without modifying its settings, but only after validating that default
encryption exactly matches `[storage] encryption`, all four S3 Block Public
Access controls are enabled, and versioning status is `Enabled`. A mismatch or
disabled control fails with a configuration error. AWS credentials and
read-only `s3:GetEncryptionConfiguration`, `s3:GetBucketPublicAccessBlock`, and
`s3:GetBucketVersioning` permissions are required for synth and deploy. Even
`--dry-run` must reach AWS for an existing-bucket check; disabling CDK context
lookups does not skip these S3 API checks. The platform never changes the
adopted bucket's configuration or lifecycle policy. The artifact bucket is
documented separately in [Security](security.md). Optional EFS, FSx, and
Mountpoint-for-S3 storage are not implemented yet.