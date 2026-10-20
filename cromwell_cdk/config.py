"""Load and validate the deployment's single INI configuration contract.

The loader is deliberately local-only: AWS resource existence and subnet/AZ
lookups belong to synthesis/deployment validation where cloud context exists.
"""

from __future__ import annotations

import configparser
import ipaddress
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cromwell_cdk.errors import ConfigError


_NAMESPACE_PATTERN = re.compile(r"^[a-z0-9-]{1,32}$")
_ALLOWED_LOG_RETENTION_DAYS = frozenset(
    {1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1827, 3653}
)
_REQUIRED_SECTIONS = frozenset(
    {
        "deployment",
        "network",
        "access",
        "storage",
        "efs",
        "fsx",
        "mountpoint_s3",
        "batch",
        "artifacts",
        "cromwell",
        "database",
        "external",
        "observability",
    }
)


@dataclass(frozen=True)
class DeploymentConfig:
    """Typed view of the operator's parsed deployment settings.

    Args:
        values: Nested section/key mapping with normalized Python values.

    Returns:
        An immutable typed configuration container.
    """

    values: dict[str, dict[str, Any]]

    def section(self, name: str) -> dict[str, Any]:
        """Return the normalized values for one configuration section.

        Args:
            name: INI section name.

        Returns:
            A read-only-by-convention mapping of normalized values.

        Raises:
            ConfigError: If the requested section is unknown.
        """
        try:
            return self.values[name]
        except KeyError as exc:
            raise ConfigError(f"Unknown configuration section [{name}]") from exc

    def get(self, section: str, key: str) -> Any:
        """Return a normalized setting by section and key.

        Args:
            section: INI section name.
            key: Key in the section.

        Returns:
            The normalized setting value.

        Raises:
            ConfigError: If the section or setting does not exist.
        """
        try:
            return self.section(section)[key]
        except KeyError as exc:
            raise ConfigError(f"Missing configuration key [{section}] {key}") from exc


def _split_csv(raw_value: str) -> list[str]:
    """Split a comma-delimited value, dropping empty entries."""
    return [part.strip() for part in raw_value.split(",") if part.strip()]


def _parse_value(raw_value: str, default: Any) -> Any:
    """Parse a scalar or comma-separated list according to its default type."""
    if isinstance(default, bool):
        lowered = raw_value.strip().lower()
        if lowered not in {"true", "false", "yes", "no", "1", "0", "on", "off"}:
            raise ValueError(f"expected a boolean value, got {raw_value!r}")
        return lowered in {"true", "yes", "1", "on"}
    if isinstance(default, int):
        return int(raw_value.strip())
    if isinstance(default, float):
        return float(raw_value.strip())
    if isinstance(default, list):
        return _split_csv(raw_value)
    return raw_value.strip()


def _defaults() -> dict[str, dict[str, Any]]:
    """Return the canonical typed defaults for all supported settings."""
    return {
        "deployment": {"namespace": "",},
        "network": {"vpc_id": "", "private_subnet_ids": []},
        "access": {"public_access": False, "allowed_cidrs": []},
        "storage": {
            "existing_bucket": False,
            "removal_policy": "RETAIN",
            "encryption": "SSE_KMS",
        },
        "efs": {"create": False, "existing_file_system_ids": []},
        "fsx": {
            "create": False,
            "storage_type": "SSD",
            "storage_capacity_gib": 1200,
            "per_unit_throughput": 200,
        },
        "mountpoint_s3": {
            "primary_bucket_mount": False,
            "best_effort_mounts": False,
            **{
                f"mount{index}_{suffix}": ("ro" if suffix == "access_mode" else "")
                for index in range(1, 6)
                for suffix in ("bucket", "prefix", "access_mode")
            },
        },
        "batch": {
            "default_use_spot": True,
            "default_min_vcpus": 0,
            "default_max_vcpus": 256,
            "priority_min_vcpus": 0,
            "priority_max_vcpus": 64,
            "instance_types": ["m5.large", "m5.xlarge"],
            "spot_bid_percentage": 100,
        },
        "artifacts": {
            "verify_checksums": True,
            "artifact_bucket_removal_policy": "RETAIN",
        },
        "cromwell": {
            "hosted": False,
            "instance_type": "t3.large",
            "version": "87",
            "tls_certificate_arn": "",
        },
        "database": {
            "hosted": False,
            "standalone_ok": False,
            "engine_version": "",
            "min_acu": 0.5,
            "max_acu": 8.0,
            "removal_policy": "SNAPSHOT",
        },
        "external": {"source_cidrs": [], "ports": []},
        "observability": {"log_retention_days": 30},
    }


def load_config(path: str | Path) -> DeploymentConfig:
    """Read the INI file and normalize every documented setting.

    Args:
        path: Path to a deployment INI file.

    Returns:
        Parsed, normalized deployment configuration.

    Raises:
        ConfigError: If the file cannot be read or contains malformed values.
    """
    config_path = Path(path)
    parser = configparser.ConfigParser(interpolation=None)
    try:
        loaded = parser.read(config_path)
    except (OSError, configparser.Error) as exc:
        raise ConfigError(f"Unable to read configuration file {config_path}: {exc}") from exc
    if not loaded:
        raise ConfigError(f"Configuration file not found or unreadable: {config_path}")

    unknown_sections = sorted(set(parser.sections()) - _REQUIRED_SECTIONS)
    if unknown_sections:
        unknown = ", ".join(f"[{section}]" for section in unknown_sections)
        raise ConfigError(f"Unknown configuration section(s): {unknown}")

    missing_sections = sorted(_REQUIRED_SECTIONS - set(parser.sections()))
    if missing_sections:
        missing = ", ".join(f"[{section}]" for section in missing_sections)
        raise ConfigError(f"Missing required configuration sections: {missing}")

    values = _defaults()
    for section, defaults in values.items():
        unknown_keys = sorted(set(parser.options(section)) - set(defaults))
        if unknown_keys:
            unknown = ", ".join(unknown_keys)
            raise ConfigError(f"Unknown configuration key(s) in [{section}]: {unknown}")
        for key, default in defaults.items():
            if not parser.has_option(section, key):
                continue
            raw_value = parser.get(section, key)
            try:
                values[section][key] = _parse_value(raw_value, default)
            except (ValueError, OverflowError) as exc:
                raise ConfigError(
                    f"Invalid value for [{section}] {key}: {exc}"
                ) from exc
    return DeploymentConfig(values)


def validate_config(config: DeploymentConfig) -> None:
    """Validate deterministic configuration invariants before synthesis.

    Args:
        config: Parsed configuration returned by :func:`load_config`.
    Raises:
        ConfigError: If any value violates the deployment contract.
    """
    namespace = config.get("deployment", "namespace")
    if not _NAMESPACE_PATTERN.fullmatch(namespace):
        raise ConfigError(
            "Invalid [deployment] namespace: expected 1-32 lowercase letters, "
            "digits, or hyphens"
        )

    vpc_id = config.get("network", "vpc_id")
    if not re.fullmatch(r"vpc-[0-9a-fA-F]{8,17}", vpc_id):
        raise ConfigError("Invalid [network] vpc_id: expected a VPC identifier")
    subnet_ids = config.get("network", "private_subnet_ids")
    if len(subnet_ids) < 2 or len(set(subnet_ids)) != len(subnet_ids):
        raise ConfigError(
            "Invalid [network] private_subnet_ids: at least two distinct subnet IDs are required"
        )
    if any(not re.fullmatch(r"subnet-[0-9a-fA-F]{8,17}", item) for item in subnet_ids):
        raise ConfigError("Invalid [network] private_subnet_ids: malformed subnet ID")

    access = config.section("access")
    cromwell = config.section("cromwell")
    if access["public_access"]:
        if not access["allowed_cidrs"]:
            raise ConfigError("Invalid [access] allowed_cidrs: required for public access")
        _validate_cidrs(access["allowed_cidrs"], "[access] allowed_cidrs")
        if not cromwell["hosted"]:
            raise ConfigError("Invalid [access] public_access: requires [cromwell] hosted = true")
        if not cromwell["tls_certificate_arn"]:
            raise ConfigError(
                "Invalid [cromwell] tls_certificate_arn: required for public access"
            )
    elif access["allowed_cidrs"]:
        _validate_cidrs(access["allowed_cidrs"], "[access] allowed_cidrs")

    if cromwell["hosted"]:
        version = str(cromwell["version"]).strip().lower()
        if not version or version == "latest":
            raise ConfigError("Invalid [cromwell] version: a pinned release is required")

    database = config.section("database")
    if not math.isfinite(database["min_acu"]) or not math.isfinite(database["max_acu"]):
        raise ConfigError("Invalid [database] min_acu/max_acu: values must be finite numbers")
    if database["max_acu"] < database["min_acu"]:
        raise ConfigError("Invalid [database] max_acu: must be greater than or equal to min_acu")
    if database["hosted"] and not cromwell["hosted"] and not database["standalone_ok"]:
        raise ConfigError(
            "Invalid [database] standalone_ok: set true to host a database without Cromwell"
        )

    mountpoint = config.section("mountpoint_s3")
    for index in range(1, 6):
        access_mode = mountpoint[f"mount{index}_access_mode"]
        if access_mode not in {"ro", "rw"}:
            raise ConfigError(
                f"Invalid [mountpoint_s3] mount{index}_access_mode: expected ro or rw"
            )

    batch = config.section("batch")
    for key in ("default", "priority"):
        minimum = batch[f"{key}_min_vcpus"]
        maximum = batch[f"{key}_max_vcpus"]
        if minimum < 0 or maximum < minimum:
            raise ConfigError(
                f"Invalid [batch] {key}_max_vcpus: must be >= {key}_min_vcpus >= 0"
            )
    if batch["priority_min_vcpus"] > 0 and batch["priority_max_vcpus"] <= 0:
        raise ConfigError("Invalid [batch] priority_max_vcpus: must allow On-Demand capacity")
    if not batch["instance_types"]:
        raise ConfigError("Invalid [batch] instance_types: at least one type is required")
    if not 1 <= batch["spot_bid_percentage"] <= 100:
        raise ConfigError("Invalid [batch] spot_bid_percentage: expected 1-100")

    if config.get("artifacts", "verify_checksums") is not True:
        raise ConfigError("Invalid [artifacts] verify_checksums: must remain true")
    if database["removal_policy"] not in {"SNAPSHOT", "RETAIN", "DESTROY"}:
        raise ConfigError("Invalid [database] removal_policy: expected SNAPSHOT, RETAIN, or DESTROY")
    if config.get("storage", "removal_policy") not in {"RETAIN", "DESTROY"}:
        raise ConfigError("Invalid [storage] removal_policy: expected RETAIN or DESTROY")
    if config.get("artifacts", "artifact_bucket_removal_policy") not in {"RETAIN", "DESTROY"}:
        raise ConfigError(
            "Invalid [artifacts] artifact_bucket_removal_policy: expected RETAIN or DESTROY"
        )
    if config.get("storage", "encryption") not in {"SSE_KMS", "SSE_S3"}:
        raise ConfigError("Invalid [storage] encryption: expected SSE_KMS or SSE_S3")
    if config.get("fsx", "storage_type") not in {"SSD", "HDD", "SCRATCH"}:
        raise ConfigError("Invalid [fsx] storage_type: expected SSD, HDD, or SCRATCH")

    retention = config.get("observability", "log_retention_days")
    if retention not in _ALLOWED_LOG_RETENTION_DAYS:
        raise ConfigError(
            "Invalid [observability] log_retention_days: not supported by CloudWatch Logs"
        )


def _validate_cidrs(cidrs: list[str], key: str) -> None:
    """Validate CIDR syntax and disallow unrestricted IPv4/IPv6 sources."""
    for cidr in cidrs:
        try:
            network = ipaddress.ip_network(cidr, strict=False)
        except ValueError as exc:
            raise ConfigError(f"Invalid {key}: malformed CIDR {cidr!r}") from exc
        if network.prefixlen == 0:
            raise ConfigError(f"Invalid {key}: unrestricted CIDR {cidr!r} is prohibited")
