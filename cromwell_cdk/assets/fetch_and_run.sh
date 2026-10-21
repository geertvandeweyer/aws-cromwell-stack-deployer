#!/usr/bin/env bash
# Fetch and execute one private S3 script only after verifying its SHA-256.
set -euo pipefail

usage() {
  echo "Usage: BATCH_FILE_S3_URL=s3://bucket/key BATCH_FILE_SHA256=<64 hex chars> $0 [args...]" >&2
  exit 2
}

[[ -n "${BATCH_FILE_S3_URL:-}" ]] || usage
[[ -n "${BATCH_FILE_SHA256:-}" ]] || usage
[[ "${BATCH_FILE_S3_URL}" =~ ^s3://([^/]+)/(.+)$ ]] || usage
bucket="${BASH_REMATCH[1]}"
key="${BASH_REMATCH[2]}"
[[ "${BATCH_FILE_SHA256}" =~ ^[[:xdigit:]]{64}$ ]] || usage

aws_cli="${AWS_CLI:-aws}"
command -v "${aws_cli}" >/dev/null 2>&1 || {
  echo "AWS CLI not found: ${aws_cli}" >&2
  exit 127
}
command -v sha256sum >/dev/null 2>&1 || {
  echo "sha256sum is required" >&2
  exit 127
}

work_dir="$(mktemp -d)"
trap 'rm -rf -- "${work_dir}"' EXIT HUP INT TERM
script_path="${work_dir}/payload"

"${aws_cli}" s3 cp --only-show-errors "${BATCH_FILE_S3_URL}" "${script_path}"
actual_sha256="$(sha256sum "${script_path}" | awk '{print $1}')"
if [[ "${actual_sha256,,}" != "${BATCH_FILE_SHA256,,}" ]]; then
  echo "SHA-256 mismatch for s3://${bucket}/${key}" >&2
  exit 1
fi

chmod 0700 "${script_path}"
"${script_path}" "$@"
