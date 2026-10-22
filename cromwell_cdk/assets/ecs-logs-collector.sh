#!/usr/bin/env bash
# Collect ECS, container runtime, and operating-system diagnostics without exposing credentials.
set -Eeuo pipefail

if [[ $(id -u) -ne 0 ]]; then
  printf 'ERROR: run %s as root to collect system logs.\n' "$0" >&2
  exit 1
fi
command -v tar >/dev/null 2>&1 || { printf 'ERROR: tar is required.\n' >&2; exit 127; }

output_dir=${1:-/var/tmp/ecs-diagnostics}
work_dir=$(mktemp -d "${TMPDIR:-/tmp}/ecs-diagnostics.XXXXXXXX")
trap 'rm -rf -- "$work_dir"' EXIT
mkdir -p "$work_dir/logs" "$work_dir/system"

for file in /etc/os-release /etc/ecs/ecs.config /var/log/messages /var/log/ecs/ecs-agent.log*; do
  [[ -f "$file" ]] || continue
  target="$work_dir/logs/${file#/}"
  mkdir -p "$(dirname "$target")"
  cp -- "$file" "$target"
done
if command -v journalctl >/dev/null 2>&1; then
  journalctl --no-pager -u ecs -n 2000 > "$work_dir/logs/ecs-journal.log" 2>&1 || true
  journalctl --no-pager -u docker -n 2000 > "$work_dir/logs/docker-journal.log" 2>&1 || true
fi
if command -v docker >/dev/null 2>&1; then
  docker info > "$work_dir/system/docker-info.txt" 2>&1 || true
  docker ps --all --no-trunc > "$work_dir/system/docker-containers.txt" 2>&1 || true
fi
uname -a > "$work_dir/system/uname.txt"
df -h > "$work_dir/system/filesystems.txt"
mount > "$work_dir/system/mounts.txt"

# Redact common credential-bearing fields before archiving copied configuration/logs.
find "$work_dir" -type f -exec sed -i -E \
  -e 's/(ECS_ENGINE_AUTH_DATA=).*/\1[REDACTED]/' \
  -e 's/(AWS_SECRET_ACCESS_KEY[=:])[[:alnum:]_\/+.-]+/\1[REDACTED]/g' \
  -e 's/(AWS_SESSION_TOKEN[=:]).*/\1[REDACTED]/g' {} +
mkdir -p "$output_dir"
archive="$output_dir/ecs-diagnostics-$(date -u +%Y%m%dT%H%M%SZ).tar.gz"
tar -czf "$archive" -C "$work_dir" logs system
chmod 0600 "$archive"
printf 'Diagnostics archive created: %s\n' "$archive"
