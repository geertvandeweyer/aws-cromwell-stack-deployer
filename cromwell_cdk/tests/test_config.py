"""Unit tests for configuration loading and validation."""

from pathlib import Path

from cromwell_cdk.config import load_config, validate_config
from cromwell_cdk.errors import ConfigError
from cromwell_cdk.tests.base import TestBase


class ConfigTests(TestBase):
    """Exercise the configuration contract's deterministic behavior."""

    def setUp(self) -> None:
        """Create a complete valid configuration for each test."""
        super().setUp()
        self.config_path = Path(self.temp_dir) / "configuration.ini"
        self.write_config()

    def write_config(self, replacements: dict[str, str] | None = None) -> None:
        """Write the standard test INI, applying full-line replacements.

        Args:
            replacements: Mapping of exact INI lines to their replacement text.
        """
        content = (Path(__file__).parents[2] / "configuration.example.ini").read_text()
        for old, new in (replacements or {}).items():
            if old not in content:
                raise ValueError(f"test fixture line not found: {old}")
            content = content.replace(old, new, 1)
        self.config_path.write_text(content)

    def test_example_configuration_loads_and_validates(self) -> None:
        """Accept the shipped example's typed settings."""
        config = load_config(self.config_path)
        validate_config(config)
        self.assertEqual(config.get("deployment", "namespace"), "cromwell-prod")
        self.assertIs(config.get("artifacts", "verify_checksums"), True)
        self.assertEqual(config.get("batch", "instance_types"), ["m5.large", "m5.xlarge"])

    def test_missing_file_names_path(self) -> None:
        """Report a missing configuration file path clearly."""
        with self.assertRaisesRegex(ConfigError, "does-not-exist.ini"):
            load_config(Path(self.temp_dir) / "does-not-exist.ini")

    def test_missing_section_names_section(self) -> None:
        """Reject a configuration missing a required section."""
        self.write_config()
        text = self.config_path.read_text().replace("[external]\nsource_cidrs =\nports =\n", "")
        self.config_path.write_text(text)
        with self.assertRaisesRegex(ConfigError, r"\[external\]"):
            load_config(self.config_path)

    def test_invalid_boolean_names_key(self) -> None:
        """Reject malformed booleans with their section and key."""
        self.write_config({"public_access = false": "public_access = perhaps"})
        with self.assertRaisesRegex(ConfigError, r"\[access\] public_access"):
            load_config(self.config_path)

    def test_unknown_key_is_rejected(self) -> None:
        """Reject a typo rather than silently ignoring it."""
        with self.assertRaisesRegex(ConfigError, r"Unknown configuration key.*\[access\].*typo"):
            self.write_config()
            text = self.config_path.read_text().replace(
                "public_access = false", "public_access = false\ntypo = ignored"
            )
            self.config_path.write_text(text)
            load_config(self.config_path)

    def test_invalid_namespace_is_rejected(self) -> None:
        """Reject namespace values outside the documented pattern."""
        self.write_config({"namespace = cromwell-prod": "namespace = Cromwell_prod"})
        with self.assertRaisesRegex(ConfigError, r"\[deployment\] namespace"):
            validate_config(load_config(self.config_path))

    def test_duplicate_or_missing_private_subnets_are_rejected(self) -> None:
        """Require two distinct, syntactically valid private subnet IDs."""
        self.write_config(
            {"private_subnet_ids = subnet-aaaaaaaa, subnet-bbbbbbbb": "private_subnet_ids = subnet-aaaaaaaa, subnet-aaaaaaaa"}
        )
        with self.assertRaisesRegex(ConfigError, "at least two distinct"):
            validate_config(load_config(self.config_path))

    def test_hosted_latest_cromwell_is_rejected(self) -> None:
        """Require an immutable Cromwell release when hosting it."""
        self.write_config(
            {"hosted = false": "hosted = true", "version = 87": "version = latest"}
        )
        with self.assertRaisesRegex(ConfigError, r"\[cromwell\] version"):
            validate_config(load_config(self.config_path))

    def test_public_access_requires_allowlist_and_tls(self) -> None:
        """Require CIDR allowlisting and TLS for public hosted Cromwell."""
        self.write_config(
            {
                "public_access = false": "public_access = true",
                "hosted = false": "hosted = true",
            }
        )
        with self.assertRaisesRegex(ConfigError, r"\[access\] allowed_cidrs"):
            validate_config(load_config(self.config_path))

    def test_database_acu_range_and_standalone_guard(self) -> None:
        """Reject reversed ACU bounds and unapproved standalone databases."""
        self.write_config({"max_acu = 8": "max_acu = 0.25"})
        with self.assertRaisesRegex(ConfigError, r"\[database\] max_acu"):
            validate_config(load_config(self.config_path))
        text = Path(__file__).parents[2].joinpath("configuration.example.ini").read_text()
        text = text.replace("[database]\nhosted = false", "[database]\nhosted = true", 1)
        self.config_path.write_text(text)
        with self.assertRaisesRegex(ConfigError, r"\[database\] standalone_ok"):
            validate_config(load_config(self.config_path))

    def test_disabled_checksum_verification_is_rejected(self) -> None:
        """Prevent disabling repository asset verification."""
        self.write_config({"verify_checksums = true": "verify_checksums = false"})
        with self.assertRaisesRegex(ConfigError, r"\[artifacts\] verify_checksums"):
            validate_config(load_config(self.config_path))

    def test_non_finite_database_acu_is_rejected(self) -> None:
        """Reject NaN and infinity because they make ACU comparisons unreliable."""
        for value in ("nan", "inf", "-inf"):
            with self.subTest(value=value):
                self.write_config({"min_acu = 0.5": f"min_acu = {value}"})
                with self.assertRaisesRegex(ConfigError, r"\[database\] min_acu/max_acu"):
                    validate_config(load_config(self.config_path))

    def test_unrestricted_public_cidr_is_rejected(self) -> None:
        """Prevent a public endpoint allowlist from becoming world-open."""
        self.write_config(
            {
                "public_access = false": "public_access = true",
                "allowed_cidrs =": "allowed_cidrs = 0.0.0.0/0",
                "hosted = false": "hosted = true",
            }
        )
        with self.assertRaisesRegex(ConfigError, "unrestricted CIDR"):
            validate_config(load_config(self.config_path))

    def test_destroy_policies_are_parsed_for_later_cli_confirmation(self) -> None:
        """Accept DESTROY syntactically; the CLI owns confirmation enforcement."""
        self.write_config({"removal_policy = RETAIN": "removal_policy = DESTROY"})
        config = load_config(self.config_path)
        validate_config(config)
        self.assertEqual(config.get("storage", "removal_policy"), "DESTROY")

    def test_sixth_mount_key_is_rejected(self) -> None:
        """Reject configuration beyond the five supported Mountpoint mounts."""
        text = self.config_path.read_text().replace(
            "mount5_access_mode = ro", "mount5_access_mode = ro\nmount6_bucket = extra"
        )
        self.config_path.write_text(text)
        with self.assertRaisesRegex(ConfigError, r"\[mountpoint_s3\].*mount6_bucket"):
            load_config(self.config_path)