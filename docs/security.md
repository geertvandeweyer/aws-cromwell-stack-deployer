# Security

## Artifact execution

`cromwell_cdk/assets/fetch_and_run.sh` is the only repository asset runner
currently approved for execution. It accepts an `s3://bucket/key` object and a
64-character expected SHA-256 digest through `BATCH_FILE_S3_URL` and
`BATCH_FILE_SHA256`. The runner downloads to a private temporary directory,
verifies the digest before execution, and fails closed on missing or mismatched
checksums. Callers must obtain the expected digest from a reviewed,
repository-controlled checksum manifest; a digest supplied by the same
untrusted source as the object does not establish provenance.

The checked-in `cromwell_cdk/assets/CHECKSUMS.sha256` covers the reviewed
static assets, including the hosted Cromwell entrypoint. The Cromwell release
JAR is staged separately from its pinned official digest or an operator
override and receives a generated checksum entry; it is not checked into the
repository because of its size.

The runner does not support HTTP(S) downloads or ZIP archives. In particular,
it does not inherit the legacy `fetch_and_run.sh` behavior of executing an
arbitrary S3 object or a script extracted from a ZIP without an independently
verified manifest. The rest of the legacy ECS provisioning scripts have not
been ported: they assume ECS host layouts, perform privileged host/AWS
mutations, and use legacy SSM paths and secret names. Review and redesign them
before reuse.

The artifact bucket itself blocks S3 public access, requires TLS, uses KMS
encryption, and is versioned. Hosted bootstrap downloads all staged files and
verifies the complete manifest before starting the service.
The Cromwell JAR staging helper pins the official release digest or requires
an operator-supplied digest for a local/HTTPS override, and verifies the bytes
before staging. A custom URL must use HTTPS and cannot downgrade through a
redirect. Staged bytes are uploaded under the private `assets/` prefix. The
host verifies all assets before running the root-owned Cromwell entrypoint.

## AWS Batch role permissions

The `BatchRoles` construct defines separate service and compute roles. The
service role trusts `batch.amazonaws.com` and attaches the AWS-managed
`AWSBatchServiceRole` policy. The EC2 instance role trusts
`ec2.amazonaws.com` and attaches the AWS-managed
`AmazonEC2ContainerServiceforEC2Role` policy for ECS container-instance
operation. Its explicit S3 permissions are narrower: it can list the artifact
bucket only with the `assets/` prefix, read objects under `assets/*`, and read
and write objects in the primary workflow data bucket. These permissions do
not grant access to other artifact-bucket prefixes or wildcard S3 resources.

Operators may declare additional S3 grants in `[additional_s3_buckets]`.
These grants apply to the Batch instance role and support an optional object
prefix plus `readonly` or `full` access. `readonly` permits `ListBucket` only
within the declared prefix and `GetObject` on matching objects. `full` adds
object-level `PutObject`, `DeleteObject`, and multipart-abort actions; it does
not grant bucket administration or access to other buckets. Adding or removing
a declaration and redeploying reconciles the role policy through the stack.
For cross-account buckets, the bucket owner must also authorize the role in the
bucket policy. These additional declarations do not grant access to the
Cromwell host role.

`CromwellServerRole` is created only when hosted Cromwell is enabled. It has
read/write access to the primary workflow bucket, read access to the artifact
bucket, queue-scoped `SubmitJob`, `DescribeJobQueues`, and `ListJobs`,
job monitoring, and `iam:PassRole` constrained to the Batch instance role and
ECS task service. Job submission references the `cromwell-*` job-definition
family. Dynamic definition registration uses the Batch job-definition-name
request condition; validate the supported condition key against the target
AWS partition before production.
It can read the Aurora secret only when the hosted database is enabled and can
write to the Cromwell log group. Batch job definitions are registered
dynamically; review the rendered policy and actual Cromwell 92 backend API
calls in the target account before production use. The current role uses
`Resource: "*"` only for dynamic job-definition describe/register actions,
guarded by the job-definition-name request condition.

## Hosted Cromwell access and metadata database

The Cromwell EC2 instance is placed in a configured private subnet, requires
IMDSv2, and uses SSM for administration. Its application security group accepts
only TCP/8000 from the ALB security group. The Aurora security group accepts
only MySQL/TLS TCP/3306 from the Cromwell instance security group. The ALB is
internal by default; the optional public ALB listener is TLS-only and restricted
to explicit `allowed_cidrs`. Public access additionally requires an ACM
certificate and at least two public VPC subnets.

The Batch compute security group has no external-source ingress rules. An
operator-hosted Cromwell deployment should use a scoped IAM role or temporary
credentials and operator-managed egress/routing to AWS Batch, S3, and any
optional APIs in use. Cromwell 92's AWS Batch backend submits to queues,
registers job definitions, and describes/terminates jobs; workflow execution
uses S3. The operator must also arrange narrowly scoped `iam:PassRole` for a
job role when workflows request one. No callback port from Batch to Cromwell is
required.

Aurora credentials are generated by Secrets Manager and retrieved by the
hosted Cromwell service at startup. Automatic rotation is disabled by default
because the running JDBC pool does not refresh credentials. When
`rotate_secret = true`, operators must schedule a safe Cromwell restart or
credential refresh after rotation.