"""Offline tests for the checksum-gated S3 asset runner."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess

from cromwell_cdk.tests.base import TestBase


RUNNER = Path(__file__).parents[1] / "assets" / "fetch_and_run.sh"


class AssetRunnerTests(TestBase):
    """Verify downloaded scripts are checked before execution."""

    def setUp(self) -> None:
        """Create a fake AWS CLI and deterministic payload fixture."""
        super().setUp()
        self.bin_dir = Path(self.temp_dir) / "bin"
        self.bin_dir.mkdir()
        self.payload = Path(self.temp_dir) / "payload.sh"
        self.payload.write_text('#!/bin/sh\nprintf "ran:%s\\n" "$1"\n')
        self.download_log = Path(self.temp_dir) / "download.log"
        fake_aws = self.bin_dir / "aws"
        fake_aws.write_text(
            "#!/usr/bin/env python3\n"
            "import os, shutil, sys\n"
            "from pathlib import Path\n"
            "assert sys.argv[1:4] == ['s3', 'cp', '--only-show-errors']\n"
            "shutil.copyfile(os.environ['ASSET_TEST_PAYLOAD'], sys.argv[5])\n"
            "Path(os.environ['ASSET_TEST_DOWNLOAD_LOG']).write_text('downloaded')\n"
        )
        fake_aws.chmod(0o700)
        self.env = os.environ.copy()
        self.env.update(
            {
                "PATH": f"{self.bin_dir}:{os.environ['PATH']}",
                "ASSET_TEST_PAYLOAD": str(self.payload),
                "ASSET_TEST_DOWNLOAD_LOG": str(self.download_log),
                "BATCH_FILE_S3_URL": "s3://private-bucket/scripts/job.sh",
            }
        )

    def run_runner(self, expected_sha256: str) -> subprocess.CompletedProcess[str]:
        """Run the asset runner against the fake AWS CLI.

        Args:
            expected_sha256: Digest supplied to the runner.

        Returns:
            Completed process result.
        """
        self.env["BATCH_FILE_SHA256"] = expected_sha256
        return subprocess.run(
            ["bash", str(RUNNER), "argument"],
            check=False,
            capture_output=True,
            text=True,
            env=self.env,
        )

    def test_runner_executes_payload_after_valid_checksum(self) -> None:
        """Run a downloaded script only when its expected digest matches."""
        digest = hashlib.sha256(self.payload.read_bytes()).hexdigest()
        result = self.run_runner(digest)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "ran:argument\n")
        self.assertTrue(self.download_log.exists())

    def test_runner_checksum_matches_repository_manifest(self) -> None:
        """Keep the committed runner bytes aligned with its reviewed manifest."""
        manifest = RUNNER.with_name("CHECKSUMS.sha256")
        manifest_entry = next(
            line.split(maxsplit=1)
            for line in manifest.read_text().splitlines()
            if line.endswith("fetch_and_run.sh")
        )
        self.assertEqual(
            manifest_entry[0], hashlib.sha256(RUNNER.read_bytes()).hexdigest()
        )

    def test_runner_rejects_mismatched_checksum_before_execution(self) -> None:
        """Fail closed and do not run a payload with the wrong digest."""
        result = self.run_runner("0" * 64)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SHA-256 mismatch", result.stderr)
        self.assertNotIn("ran:argument", result.stdout)

    def test_runner_warns_and_computes_digest_when_checksum_is_missing(self) -> None:
        """Run without an expected digest only after warning and hashing locally."""
        self.env.pop("BATCH_FILE_SHA256", None)
        result = subprocess.run(
            ["bash", str(RUNNER), "argument"],
            check=False,
            capture_output=True,
            text=True,
            env=self.env,
        )
        expected_digest = hashlib.sha256(self.payload.read_bytes()).hexdigest()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("potential data corruption cannot be ruled out", result.stderr)
        self.assertIn(expected_digest, result.stderr)
        self.assertEqual(result.stdout, "ran:argument\n")
        self.assertTrue(self.download_log.exists())

    def test_runner_rejects_zip_urls(self) -> None:
        """Do not accept arbitrary archive execution as the S3 source."""
        self.env["BATCH_FILE_S3_URL"] = "https://example.invalid/archive.zip"
        self.env["BATCH_FILE_SHA256"] = "0" * 64
        result = subprocess.run(
            ["bash", str(RUNNER)],
            check=False,
            capture_output=True,
            text=True,
            env=self.env,
        )
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.download_log.exists())
