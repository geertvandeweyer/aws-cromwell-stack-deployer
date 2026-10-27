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
        self.assertIs(config.get("database", "rotate_secret"), False)
        self.assertEqual(
            config.get("batch", "instance_types"), ["m5.large", "m5.xlarge"]
        )

    def test_missing_file_names_path(self) -> None:
        """Report a missing configuration file path clearly."""
        with self.assertRaisesRegex(ConfigError, "does-not-exist.ini"):
            load_config(Path(self.temp_dir) / "does-not-exist.ini")

    def test_missing_section_names_section(self) -> None:
        """Reject a configuration missing a required section."""
        self.write_config()
        text = self.config_path.read_text().replace(
            "[external]\nsource_cidrs =\nports =\n", ""
        )
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
        with self.assertRaisesRegex(
            ConfigError, r"Unknown configuration key.*\[access\].*typo"
        ):
            self.write_config()
            text = self.config_path.read_text().replace(
                "public_access = false", "public_access = false\ntypo = ignored"
            )
            self.config_path.write_text(text)
            load_config(self.config_path)

    def test_unknown_section_is_rejected(self) -> None:
        """Reject unrecognized sections instead of silently ignoring inputs."""
        self.config_path.write_text(
            self.config_path.read_text()
            + "\n[artifact_source]\nurl = https://example.invalid/public.zip\n"
        )
        with self.assertRaisesRegex(
            ConfigError, r"Unknown configuration section.*\[artifact_source\]"
        ):
            load_config(self.config_path)

    def test_invalid_namespace_is_rejected(self) -> None:
        """Reject namespace values outside the documented pattern."""
        self.write_config({"namespace = cromwell-prod": "namespace = Cromwell_prod"})
        with self.assertRaisesRegex(ConfigError, r"\[deployment\] namespace"):
            validate_config(load_config(self.config_path))

    def test_duplicate_or_missing_private_subnets_are_rejected(self) -> None:
        """Require two distinct, syntactically valid private subnet IDs."""
        self.write_config(
            {
                "private_subnet_ids = subnet-aaaaaaaa, subnet-bbbbbbbb": "private_subnet_ids = subnet-aaaaaaaa, subnet-aaaaaaaa"
            }
        )
        with self.assertRaisesRegex(ConfigError, "at least two distinct"):
            validate_config(load_config(self.config_path))

    def test_hosted_latest_cromwell_is_rejected(self) -> None:
        """Require an immutable Cromwell release when hosting it."""
        self.write_config(
            {"hosted = false": "hosted = true", "version = 92": "version = latest"}
        )
        with self.assertRaisesRegex(ConfigError, r"\[cromwell\] version"):
            validate_config(load_config(self.config_path))

    def test_cromwell_artifact_overrides_require_a_digest(self) -> None:
        """Require a SHA-256 for local and HTTPS artifact source overrides."""
        self.write_config({"artifact_path =": "artifact_path = /tmp/cromwell.jar"})
        with self.assertRaisesRegex(ConfigError, r"\[cromwell\] sha256"):
            validate_config(load_config(self.config_path))

    def test_non_default_cromwell_version_requires_an_artifact_override(self) -> None:
        """Prevent changing the release label without changing its artifact."""
        self.write_config(
            {"hosted = false": "hosted = true", "version = 92": "version = 93"}
        )
        with self.assertRaisesRegex(ConfigError, r"non-default releases require"):
            validate_config(load_config(self.config_path))

    def test_cromwell_artifact_overrides_are_exclusive(self) -> None:
        """Reject configuring local and URL sources at the same time."""
        self.write_config(
            {
                "artifact_url =": "artifact_url = https://example.invalid/cromwell.jar",
                "artifact_path =": "artifact_path = /tmp/cromwell.jar",
                "sha256 =": "sha256 = " + "a" * 64,
            }
        )
        with self.assertRaisesRegex(ConfigError, r"artifact_url/artifact_path"):
            validate_config(load_config(self.config_path))

    def test_cromwell_artifact_url_requires_https(self) -> None:
        """Restrict remote Cromwell sources to HTTPS."""
        self.write_config(
            {
                "artifact_url =": "artifact_url = http://example.invalid/cromwell.jar",
                "sha256 =": "sha256 = " + "a" * 64,
            }
        )
        with self.assertRaisesRegex(ConfigError, r"\[cromwell\] artifact_url"):
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
        text = (
            Path(__file__).parents[2].joinpath("configuration.example.ini").read_text()
        )
        text = text.replace(
            "[database]\nhosted = false", "[database]\nhosted = true", 1
        )
        text = text.replace(
            "engine_version =", "engine_version = 8.0.mysql_aurora.3.12.0", 1
        )
        self.config_path.write_text(text)
        with self.assertRaisesRegex(ConfigError, r"\[database\] standalone_ok"):
            validate_config(load_config(self.config_path))

    def test_disabled_checksum_verification_is_rejected(self) -> None:
        """Prevent disabling repository asset verification."""
        self.write_config({"verify_checksums = true": "verify_checksums = false"})
        with self.assertRaisesRegex(ConfigError, r"\[artifacts\] verify_checksums"):
            validate_config(load_config(self.config_path))

    def test_priority_queue_cannot_use_spot(self) -> None:
        """Keep the priority queue on On-Demand capacity."""
        self.write_config({"priority_use_spot = false": "priority_use_spot = true"})
        with self.assertRaisesRegex(ConfigError, r"\[batch\] priority_use_spot"):
            validate_config(load_config(self.config_path))

    def test_non_finite_database_acu_is_rejected(self) -> None:
        """Reject NaN and infinity because they make ACU comparisons unreliable."""
        for value in ("nan", "inf", "-inf"):
            with self.subTest(value=value):
                self.write_config({"min_acu = 0.5": f"min_acu = {value}"})
                with self.assertRaisesRegex(
                    ConfigError, r"\[database\] min_acu/max_acu"
                ):
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

    def test_additional_bucket_grants_load_with_safe_defaults(self) -> None:
        """Parse sequential bucket declarations and default omitted access to read-only."""
        self.config_path.write_text(
            self.config_path.read_text().replace(
                "[additional_s3_buckets]",
                "[additional_s3_buckets]\n"
                "bucket1_name = shared-inputs\n"
                "bucket1_prefix = cohort-a/\n"
                "bucket2_name = shared-results\n"
                "bucket2_access = full",
            )
        )
        config = load_config(self.config_path)
        validate_config(config)
        self.assertEqual(
            config.get("additional_s3_buckets", "1"),
            {"name": "shared-inputs", "prefix": "cohort-a/", "access": "readonly"},
        )
        self.assertEqual(
            config.get("additional_s3_buckets", "2"),
            {"name": "shared-results", "prefix": "", "access": "full"},
        )

    def test_additional_bucket_indexes_must_be_sequential(self) -> None:
        """Reject gaps in bucket indexes to avoid silently skipped declarations."""
        self.config_path.write_text(
            self.config_path.read_text().replace(
                "[additional_s3_buckets]",
                "[additional_s3_buckets]\nbucket2_name = shared-inputs",
            )
        )
        with self.assertRaisesRegex(ConfigError, "indexes must be sequential"):
            load_config(self.config_path)

    def test_additional_bucket_declaration_requires_name(self) -> None:
        """Reject partially declared indexed buckets without a name."""
        self.config_path.write_text(
            self.config_path.read_text().replace(
                "[additional_s3_buckets]",
                "[additional_s3_buckets]\nbucket1_access = readonly",
            )
        )
        with self.assertRaisesRegex(ConfigError, r"bucket1_name: required"):
            load_config(self.config_path)

    def test_additional_bucket_rejects_invalid_names_modes_and_prefixes(self) -> None:
        """Validate the bucket identifier, access mode, and safe prefix contract."""
        invalid_values = (
            ("bucket1_name = shared-inputs", "bucket1_name = Invalid_Bucket"),
            ("bucket1_access = readonly", "bucket1_access = admin"),
            ("bucket1_prefix = cohort-a/", "bucket1_prefix = cohort-*/"),
        )
        for old, new in invalid_values:
            with self.subTest(new=new):
                self.write_config()
                self.config_path.write_text(
                    self.config_path.read_text().replace(
                        "[additional_s3_buckets]",
                        "[additional_s3_buckets]\n"
                        "bucket1_name = shared-inputs\n"
                        "bucket1_prefix = cohort-a/\n"
                        "bucket1_access = readonly",
                    )
                )
                self.config_path.write_text(
                    self.config_path.read_text().replace(old, new)
                )
                with self.assertRaisesRegex(ConfigError, r"\[additional_s3_buckets\]"):
                    validate_config(load_config(self.config_path))

    def test_additional_bucket_rejects_unknown_declaration_key(self) -> None:
        """Reject typos in the indexed additional bucket syntax."""
        self.config_path.write_text(
            self.config_path.read_text().replace(
                "[additional_s3_buckets]",
                "[additional_s3_buckets]\nbucket1_typo = shared-inputs",
            )
        )
        with self.assertRaisesRegex(ConfigError, "Unknown configuration key"):
            load_config(self.config_path)
