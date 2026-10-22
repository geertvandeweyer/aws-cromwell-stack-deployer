#!/usr/bin/env bash
# Expose the AWS CLI v2 binary and its bundled libraries to containers.
set -Eeuo pipefail

SCRIPT_PATH=$(readlink -f -- "${BASH_SOURCE[0]}")
BIN_DIR=$(dirname -- "$SCRIPT_PATH")
DIST_DIR="$(dirname -- "$BIN_DIR")/dist"
AWS_BINARY="${DIST_DIR}/aws"

if [[ ! -x "$AWS_BINARY" ]]; then
  printf 'ERROR: AWS CLI v2 binary not found at %s.\n' "$AWS_BINARY" >&2
  exit 127
fi
export LD_LIBRARY_PATH="${DIST_DIR}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
exec "$AWS_BINARY" "$@"
