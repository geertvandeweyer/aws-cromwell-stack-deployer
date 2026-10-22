#!/usr/bin/env bash
# Configure ECS worker defaults, Batch fetch-and-run helper, and container AWS CLI shim.
set -Eeuo pipefail

ECS_CONFIG=/etc/ecs/ecs.config
ASSET_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
AWS_CLI_ROOT=/opt/aws-cli
AWS_CLI_BIN=/usr/local/aws-cli/v2/current/bin

if [[ ! -d "$AWS_CLI_ROOT/bin" || ! -x "$AWS_CLI_ROOT/bin/aws" ]]; then
  printf 'ERROR: expected AWS CLI v2 installation under %s\n' "$AWS_CLI_ROOT" >&2
  exit 1
fi
install -d -m 0755 /etc/ecs /usr/local/bin "$AWS_CLI_ROOT/dist" "$AWS_CLI_ROOT/bin" "$AWS_CLI_BIN"

defaults=(
  ECS_ENABLE_SPOT_INSTANCE_DRAINING=true
  ECS_IMAGE_PULL_BEHAVIOR=prefer-cached
  ECS_CONTAINER_STOP_TIMEOUT=60
  ECS_IMAGE_CLEANUP_INTERVAL=5m
  ECS_IMAGE_MINIMUM_CLEANUP_AGE=60m
)
for setting in "${defaults[@]}"; do
  key=${setting%%=*}
  if ! grep -q "^${key}=" "$ECS_CONFIG" 2>/dev/null; then
    printf '%s\n' "$setting" >> "$ECS_CONFIG"
  fi
done

if [[ -f "$ASSET_DIR/fetch_and_run.sh" ]]; then
  install -m 0755 "$ASSET_DIR/fetch_and_run.sh" /usr/local/bin/fetch_and_run.sh
fi
install -m 0755 "$ASSET_DIR/awscli-shim.sh" "$AWS_CLI_ROOT/bin/aws"

if [[ -x "$AWS_CLI_BIN/aws" && ! -e "$AWS_CLI_ROOT/dist/aws" ]]; then
  mv "$AWS_CLI_BIN" "$AWS_CLI_ROOT/dist"
  install -d -m 0755 "$AWS_CLI_BIN"
fi
if [[ -x "$AWS_CLI_ROOT/dist/aws" ]]; then
  install -m 0755 "$ASSET_DIR/awscli-shim.sh" "$AWS_CLI_BIN/aws"
  ln -sfn "$AWS_CLI_ROOT/dist/aws" /usr/bin/aws
fi
