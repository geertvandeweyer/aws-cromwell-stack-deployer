#!/usr/bin/env bash
# Install optional ECR-compatible Docker registry auth only when its secret is configured.
set -Eeuo pipefail

secret_name=${CROMWELL_DOCKERHUB_SECRET_NAME:-}
if [[ -z "$secret_name" ]]; then
  printf 'Docker Hub credentials are not configured; using anonymous registry access.\n'
  exit 0
fi

if ! command -v aws >/dev/null 2>&1 || ! command -v jq >/dev/null 2>&1; then
  printf 'ERROR: aws CLI and jq are required to load configured Docker registry credentials.\n' >&2
  exit 1
fi

secret_string=$(aws secretsmanager get-secret-value \
  --secret-id "$secret_name" \
  --query SecretString \
  --output text)
if [[ -z "$secret_string" || "$secret_string" == None ]]; then
  printf 'ERROR: secret %s did not contain a SecretString.\n' "$secret_name" >&2
  exit 1
fi

# Validate and safely JSON-encode the secret value for ECS_ENGINE_AUTH_DATA.
printf '%s' "$secret_string" | jq -e 'type == "object"' >/dev/null || {
  printf 'ERROR: secret %s must be a Docker auth JSON object.\n' "$secret_name" >&2
  exit 1
}
auth_data=$(jq -cn --argjson auth "$secret_string" '{"https://index.docker.io/v1/": $auth}')
install -d -m 0755 /etc/ecs
printf 'ECS_ENGINE_AUTH_TYPE=docker\nECS_ENGINE_AUTH_DATA=%s\n' "$auth_data" >> /etc/ecs/ecs.config
chmod 0600 /etc/ecs/ecs.config
