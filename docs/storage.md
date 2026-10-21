# Storage

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

Setting `[storage] existing_bucket = true` currently fails closed. Existing
bucket security validation and adoption are not implemented yet; do not treat
the setting as permission to use an unvalidated bucket. The artifact bucket is
documented separately in [Security](security.md). Optional EFS, FSx, and
Mountpoint-for-S3 storage are not implemented yet.