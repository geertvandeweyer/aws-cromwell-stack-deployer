#!/usr/bin/env bash
# Install configured Mountpoint for Amazon S3 mounts using operator-supplied SSM data.
set -Eeuo pipefail

: "${ARTIFACTS_NAMESPACE:?ARTIFACTS_NAMESPACE must be configured}"
PARAMETER_NAME=${MOUNTPOINT_S3_PARAMETER_NAME:-"/${ARTIFACTS_NAMESPACE}/mountpoint-s3-buckets"}
WRITE_PART_SIZE=${MOUNTPOINT_S3_WRITE_PART_SIZE:-8388608}
CACHE_MOUNT=${MOUNTPOINT_S3_CACHE_MOUNT:-/mnt/mp-cache}
CACHE_SIZE_GB=${MOUNTPOINT_S3_CACHE_SIZE_GB:-75}
CACHE_TAG_KEY=mountpoint-s3-cache

TOKEN=$(curl --fail --silent --show-error -X PUT \
  'http://169.254.169.254/latest/api/token' \
  -H 'X-aws-ec2-metadata-token-ttl-seconds: 21600')
metadata() {
  curl --fail --silent --show-error \
    -H "X-aws-ec2-metadata-token: ${TOKEN}" \
    "http://169.254.169.254/latest/meta-data/$1"
}
INSTANCE_ID=$(metadata instance-id)
AZ=$(metadata placement/availability-zone)
REGION=${AZ%?}

mounts_json=$(aws ssm get-parameter --region "$REGION" --name "$PARAMETER_NAME" \
  --query Parameter.Value --output text)
if ! jq -e 'type == "array" and all(.[]; . == null or ((.bucket | type) == "string" and (.bucket | length) > 0 and ((.access // "rw") == "ro" or (.access // "rw") == "rw")))' \
  <<< "$mounts_json" >/dev/null; then
  printf 'ERROR: SSM parameter %s must contain an array of valid mount definitions.\n' "$PARAMETER_NAME" >&2
  exit 1
fi
active_mounts=$(jq -c '[.[] | select(. != null)]' <<< "$mounts_json")
if [[ $(jq 'length' <<< "$active_mounts") -eq 0 ]]; then
  printf 'No Mountpoint for Amazon S3 mounts configured.\n'
  exit 0
fi

if ! command -v mount-s3 >/dev/null 2>&1; then
  dnf install -y mount-s3
fi
command -v mount-s3 >/dev/null

install -d -m 0755 "$(dirname "$CACHE_MOUNT")" "$CACHE_MOUNT"
if ! mountpoint --quiet "$CACHE_MOUNT"; then
  volume_id=$(aws ec2 describe-volumes --region "$REGION" \
    --filters "Name=attachment.instance-id,Values=${INSTANCE_ID}" \
              "Name=tag:${CACHE_TAG_KEY},Values=true" \
    --query 'Volumes[0].VolumeId' --output text)
  if [[ "$volume_id" == None || -z "$volume_id" ]]; then
    volume_id=$(aws ec2 create-volume --region "$REGION" \
      --availability-zone "$AZ" --volume-type gp3 --size "$CACHE_SIZE_GB" \
      --encrypted \
      --tag-specifications "ResourceType=volume,Tags=[{Key=${CACHE_TAG_KEY},Value=true},{Key=Name,Value=mountpoint-s3-cache-${INSTANCE_ID}}]" \
      --query VolumeId --output text)
    aws ec2 wait volume-available --region "$REGION" --volume-ids "$volume_id"
    aws ec2 attach-volume --region "$REGION" --volume-id "$volume_id" \
      --instance-id "$INSTANCE_ID" --device /dev/sdh
    aws ec2 wait volume-in-use --region "$REGION" --volume-ids "$volume_id"
  fi
  device_id=${volume_id//-/}
  device=''
  for attempt in {1..30}; do
    for candidate in "/dev/disk/by-id/nvme-Amazon_Elastic_Block_Store_${device_id}" /dev/sdh /dev/xvdh; do
      if [[ -e "$candidate" ]]; then
        device=$(readlink -f "$candidate")
        break 2
      fi
    done
    sleep 2
  done
  if [[ -z "$device" ]]; then
    printf 'ERROR: could not resolve attached cache volume %s.\n' "$volume_id" >&2
    exit 1
  fi
  blkid "$device" >/dev/null 2>&1 || mkfs.xfs "$device"
  cache_uuid=$(blkid -s UUID -o value "$device")
  if ! grep -qF "$cache_uuid" /etc/fstab; then
    printf 'UUID=%s %s xfs defaults,nofail 0 2\n' "$cache_uuid" "$CACHE_MOUNT" >> /etc/fstab
  fi
  mount "$CACHE_MOUNT"
  chmod 0777 "$CACHE_MOUNT"
fi

tmp_dir=$(mktemp -d)
trap 'rm -rf -- "$tmp_dir"' EXIT
whole_buckets=$(jq -r '[.[] | select(. != null and ((.prefix // "") == "")) | .bucket] | unique | .[]' <<< "$mounts_json")
while IFS= read -r item; do
  [[ -n "$item" ]] || continue
  bucket=$(jq -r '.bucket' <<< "$item")
  prefix=$(jq -r '.prefix // "" | sub("/+$"; "")' <<< "$item")
  access=$(jq -r '.access // "rw"' <<< "$item")
  if [[ -n "$prefix" ]] && grep -qxF "$bucket" <<< "$whole_buckets"; then
    printf 'Skipping redundant s3://%s/%s mount.\n' "$bucket" "$prefix"
    continue
  fi

  mount_path="/mnt/${bucket}"
  cache_key=${bucket}/${prefix}
  if [[ -n "$prefix" ]]; then
    mount_path+="/${prefix}"
  fi
  slot_cache="${CACHE_MOUNT}/$(sed 's#/*$##; s#/#_#g' <<< "$cache_key")"
  install -d -m 0755 "$mount_path" "$slot_cache"
  mount_args=("$bucket" "$mount_path" --write-part-size "$WRITE_PART_SIZE" --allow-other --cache "$slot_cache")
  if [[ -n "$prefix" ]]; then
    mount_args+=(--prefix "${prefix}/")
  fi
  if [[ "$access" == ro ]]; then
    mount_args+=(--read-only)
  else
    mount_args+=(--allow-delete --allow-overwrite)
  fi
  if ! mount-s3 "${mount_args[@]}"; then
    printf 'ERROR: failed to mount s3://%s/%s at %s.\n' "$bucket" "$prefix" "$mount_path" >&2
    exit 1
  fi
done < <(jq -c '.[] | select(. != null)' <<< "$mounts_json")

printf 'Mountpoint for Amazon S3 provisioning completed.\n'
