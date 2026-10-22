#!/usr/bin/env bash
# Checksum-gated AWS Batch fetch-and-run helper.
set -Eeuo pipefail

BASENAME=${0##*/}
AWS=${AWS_CLI_PATH:-/usr/local/aws-cli/v2/current/bin/aws}
usage() {
  printf 'Usage: BATCH_FILE_TYPE=script BATCH_FILE_S3_URL=s3://bucket/key %s [arguments...]\n' "$BASENAME" >&2
  exit 2
}
fail() {
  printf '%s: %s\n' "$BASENAME" "$1" >&2
  exit 1
}

[[ ${BATCH_FILE_TYPE:-script} == script ]] || usage
url=${BATCH_FILE_S3_URL:-}
[[ "$url" =~ ^s3://([^/]+)/(.+)$ ]] || usage
bucket=${BASH_REMATCH[1]}
key=${BASH_REMATCH[2]}
expected=${BATCH_FILE_SHA256:-}
[[ -n "$expected" ]] || usage
[[ "$expected" =~ ^[[:xdigit:]]{64}$ ]] || fail 'BATCH_FILE_SHA256 must contain a SHA-256 hex digest'
if ! command -v "$AWS" >/dev/null 2>&1; then
  AWS=$(command -v aws || true)
fi
[[ -n "$AWS" && -x "$AWS" ]] || fail 'AWS CLI executable not found'
command -v sha256sum >/dev/null 2>&1 || fail 'sha256sum is required'

work_dir=$(mktemp -d "${TMPDIR:-/tmp}/batch-file.XXXXXXXX") || fail 'Unable to create temporary directory'
cleanup() {
  if [[ ${KEEP_BATCH_FILE_CONTENTS:-} ]]; then
    printf 'Keeping downloaded Batch script at %s\n' "$work_dir" >&2
  else
    rm -rf -- "$work_dir"
  fi
}
trap cleanup EXIT
payload=${work_dir}/payload

for attempt in {1..5}; do
  if "$AWS" s3 cp --only-show-errors "$url" "$payload"; then
    actual=$(sha256sum "$payload" | awk '{print $1}')
    if [[ ${actual,,} != ${expected,,} ]]; then
      fail "SHA-256 mismatch for s3://${bucket}/${key} (expected ${expected,,}, got ${actual,,})"
    fi
    chmod 0700 "$payload"
    exec "$payload" "$@"
  fi
  if (( attempt == 5 )); then
    fail "Unable to download s3://${bucket}/${key} after $attempt attempts"
  fi
  sleep $((attempt * 2))
done
