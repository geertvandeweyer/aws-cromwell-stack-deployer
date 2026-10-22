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

The checked-in `cromwell_cdk/assets/CHECKSUMS.sha256` currently covers this
runner only. The Cromwell release JAR is staged separately from its pinned
official digest or an operator override and receives a generated checksum
entry; it is not checked into the repository because of its size.

The runner does not support HTTP(S) downloads or ZIP archives. In particular,
it does not inherit the legacy `fetch_and_run.sh` behavior of executing an
arbitrary S3 object or a script extracted from a ZIP without an independently
verified manifest. The rest of the legacy ECS provisioning scripts have not
been ported: they assume ECS host layouts, perform privileged host/AWS
mutations, and use legacy SSM paths and secret names. Review and redesign them
before reuse.

The artifact bucket itself blocks S3 public access, requires TLS, uses KMS
encryption, and is versioned. Asset upload, a signed/checked-in complete
checksum manifest, and the pinned Cromwell release archive are still pending.
The Cromwell JAR staging helper pins the official release digest or requires
an operator-supplied digest for a local/HTTPS override, and verifies the bytes
before staging. A custom URL must use HTTPS and cannot downgrade through a
redirect. Staged bytes are not runtime-executable until private-bucket upload
and host bootstrapping are implemented; the bucket should not yet be treated
as a usable runtime artifact source.