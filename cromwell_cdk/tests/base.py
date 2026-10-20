"""Shared test-case utilities for Cromwell CDK tests."""

from tempfile import TemporaryDirectory
import unittest


class TestBase(unittest.TestCase):
    """Base test case with an automatically cleaned temporary directory."""

    def setUp(self) -> None:
        """Create per-test temporary resources."""
        super().setUp()
        temporary_directory = TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.temp_dir = temporary_directory.name
