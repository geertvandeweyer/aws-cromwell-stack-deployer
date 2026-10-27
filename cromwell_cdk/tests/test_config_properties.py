"""Property-based checks for configuration validation boundaries."""

import logging
import ipaddress
import string
from pathlib import Path

from hypothesis import given, settings, strategies as st

from cromwell_cdk.config import load_config, validate_config
from cromwell_cdk.errors import ConfigError
from cromwell_cdk.tests.base import TestBase


class ConfigPropertyTests(TestBase):
    """Exercise generated input values that challenge parser invariants."""

    @settings(max_examples=100, derandomize=True)
    @given(
        namespace=st.text(
            alphabet=string.ascii_letters + string.digits + "_-!.",
            min_size=0,
            max_size=40,
        )
    )
    def test_namespace_acceptance_matches_contract(self, namespace: str) -> None:
        """Accept only non-empty lowercase alphanumeric/hyphen names up to 32 chars.

        Args:
            namespace: Generated namespace candidate.
        """
        logging.getLogger(__name__).info("Hypothesis example namespace=%r", namespace)
        example = (Path(__file__).parents[2] / "configuration.example.ini").read_text()
        example = example.replace(
            "namespace = cromwell-prod", f"namespace = {namespace}", 1
        )
        path = Path(self.temp_dir) / "configuration.ini"
        path.write_text(example)
        config = load_config(path)
        allowed = 1 <= len(namespace) <= 32 and all(
            character in string.ascii_lowercase + string.digits + "-"
            for character in namespace
        )
        if allowed:
            validate_config(config)
        else:
            with self.assertRaises(ConfigError):
                validate_config(config)

    @settings(max_examples=80, derandomize=True)
    @given(
        cidr=st.text(
            alphabet=string.ascii_letters + string.digits + ".:/_-",
            min_size=0,
            max_size=48,
        )
    )
    def test_generated_public_cidrs_never_allow_unrestricted_or_malformed(
        self, cidr: str
    ) -> None:
        """Reject malformed and unrestricted public CIDR values.

        Args:
            cidr: Generated CIDR candidate.
        """
        logging.getLogger(__name__).info("Hypothesis example CIDR=%r", cidr)
        example = (Path(__file__).parents[2] / "configuration.example.ini").read_text()
        example = example.replace("public_access = false", "public_access = true", 1)
        example = example.replace("hosted = false", "hosted = true", 1)
        example = example.replace("allowed_cidrs =", f"allowed_cidrs = {cidr}", 1)
        example = example.replace(
            "tls_certificate_arn =",
            "tls_certificate_arn = arn:aws:acm:us-east-1:123456789012:certificate/test",
            1,
        )
        path = Path(self.temp_dir) / "public.ini"
        path.write_text(example)
        config = load_config(path)
        try:
            network = ipaddress.ip_network(cidr, strict=False)
            should_be_accepted = bool(cidr) and network.prefixlen > 0
        except ValueError:
            should_be_accepted = False

        if should_be_accepted:
            validate_config(config)
        else:
            with self.assertRaisesRegex(ConfigError, "allowed_cidrs|unrestricted CIDR"):
                validate_config(config)
