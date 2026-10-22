#!/usr/bin/env bash
# Provision an ECS-optimized Amazon Linux 2023 Batch worker without legacy autoscaler hooks.
set -Eeuo pipefail

SCRIPT_DIR=${ASSET_DIRECTORY:-"$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"}

for script in ecs-additions-common.sh ecs-additions-mountpoint-s3.sh ecs-additions-cromwell.sh; do
  path="${SCRIPT_DIR}/${script}"
  if [[ ! -f "$path" ]]; then
    printf 'ERROR: required provisioning asset is missing: %s\n' "$path" >&2
    exit 1
  fi
  /usr/bin/env bash "$path"
done

printf 'Batch worker provisioning completed successfully.\n'
