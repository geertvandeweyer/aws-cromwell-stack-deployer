#!/usr/bin/env bash
# Configure ECS worker defaults and the Batch fetch-and-run helper.
set -Eeuo pipefail

ECS_CONFIG=/etc/ecs/ecs.config
ASSET_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
AWS=/usr/local/aws-cli/v2/current/bin/aws

if [[ ! -x "$AWS" ]]; then
  printf 'ERROR: expected AWS CLI v2 installation at %s\n' "$AWS" >&2
  exit 1
fi
install -d -m 0755 /etc/ecs /usr/local/bin

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
ln -sfn "$AWS" /usr/local/bin/aws
