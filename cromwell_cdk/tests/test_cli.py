"""Tests for CLI parsing, validation, subprocess handling, and exit codes."""

from pathlib import Path
from unittest.mock import Mock, patch

from cromwell_cdk.cli import (
    EXIT_CONFIGURATION,
    EXIT_INVALID_ARGUMENTS,
    EXIT_OPERATION,
    EXIT_PREREQUISITE,
    EXIT_SUCCESS,
    build_parser,
    execute,
    main,
)
from cromwell_cdk.tests.base import TestBase


class CliTests(TestBase):
    """Verify command-line behavior without launching AWS-mutating operations."""

    def setUp(self) -> None:
        """Create a temporary valid INI path for CLI invocations."""
        super().setUp()
        self.config_path = Path(self.temp_dir) / "configuration.ini"
        example = Path(__file__).parents[2] / "configuration.example.ini"
        self.config_path.write_text(example.read_text())

    def arguments(self, *extra: str) -> list[str]:
        """Build required argument tokens plus per-test additions."""
        return [
            "--region",
            "eu-west-1",
            "--cromwell-root-bucket",
            "example-root-bucket",
            "--config",
            str(self.config_path),
            *extra,
        ]

    def test_parser_requires_region_and_root_bucket(self) -> None:
        """Require the deployment region and primary Cromwell bucket."""
        parser = build_parser()
        with patch("sys.stderr") as stderr, self.assertRaises(SystemExit) as error:
            parser.parse_args([])
        self.assertEqual(error.exception.code, EXIT_INVALID_ARGUMENTS)
        self.assertTrue(stderr.write.called)

    def test_parser_exposes_supported_actions_and_defaults(self) -> None:
        """Use synth by default and accept the supported operation flags."""
        args = build_parser().parse_args(
            self.arguments("--profile", "local", "--dry-run")
        )
        self.assertEqual(args.action, "synth")
        self.assertTrue(args.dry_run)
        self.assertEqual(args.profile, "local")
        self.assertFalse(args.confirm_destroy_data)

    def test_explicit_actions_are_honored_without_dry_run(self) -> None:
        """Run deploy or destroy only when that action is explicitly requested."""
        for action in ("deploy", "destroy"):
            with self.subTest(action=action):
                args = build_parser().parse_args(self.arguments("--action", action))
                with patch("cromwell_cdk.cli._run_cdk") as run_cdk:
                    self.assertEqual(execute(args), EXIT_SUCCESS)
                run_cdk.assert_called_once_with(args, action)

    def test_default_action_synthesizes(self) -> None:
        """Synthesize by default when no action is selected."""
        args = build_parser().parse_args(self.arguments())
        with patch("cromwell_cdk.cli._run_cdk") as run_cdk:
            self.assertEqual(execute(args), EXIT_SUCCESS)
        run_cdk.assert_called_once_with(args, "synth")

    @patch("cromwell_cdk.cli._run_cdk")
    def test_dry_run_invokes_only_synth(self, run_cdk: Mock) -> None:
        """Route dry-run to synth regardless of the selected action."""
        args = build_parser().parse_args(
            self.arguments("--dry-run", "--action", "deploy")
        )
        self.assertEqual(execute(args), EXIT_SUCCESS)
        run_cdk.assert_called_once_with(args, "synth")

    def test_invalid_configuration_maps_to_exit_three(self) -> None:
        """Report deterministic configuration failures with code 3."""
        self.config_path.write_text("[deployment]\nnamespace = INVALID\n")
        args = build_parser().parse_args(self.arguments())
        with patch("sys.stderr") as stderr:
            self.assertEqual(execute(args), EXIT_CONFIGURATION)
        diagnostic = "".join(call.args[0] for call in stderr.write.call_args_list)
        self.assertIn("required configuration sections", diagnostic)

    def test_missing_configuration_maps_to_exit_three(self) -> None:
        """Treat a missing configuration file as a configuration error."""
        args = build_parser().parse_args(
            [
                "--region",
                "eu-west-1",
                "--cromwell-root-bucket",
                "example-root-bucket",
                "--config",
                str(Path(self.temp_dir) / "missing.ini"),
            ]
        )
        with patch("sys.stderr") as stderr:
            self.assertEqual(execute(args), EXIT_CONFIGURATION)
        diagnostic = "".join(call.args[0] for call in stderr.write.call_args_list)
        self.assertIn("Configuration file", diagnostic)

    def test_invalid_root_bucket_maps_to_exit_two(self) -> None:
        """Reject an empty required root bucket before invoking CDK."""
        args = build_parser().parse_args(
            [
                "--region",
                "eu-west-1",
                "--cromwell-root-bucket",
                "",
                "--config",
                str(self.config_path),
            ]
        )
        with patch("sys.stderr") as stderr:
            self.assertEqual(execute(args), EXIT_INVALID_ARGUMENTS)
        self.assertTrue(stderr.write.called)

    def test_invalid_root_bucket_precedes_invalid_config_in_main(self) -> None:
        """Return argument exit code before attempting an invalid config file."""
        with patch("sys.stderr") as stderr:
            result = main(
                [
                    "--region",
                    "eu-west-1",
                    "--cromwell-root-bucket",
                    "",
                    "--config",
                    str(Path(self.temp_dir) / "missing.ini"),
                ]
            )
        self.assertEqual(result, EXIT_INVALID_ARGUMENTS)
        diagnostic = "".join(call.args[0] for call in stderr.write.call_args_list)
        self.assertIn("--cromwell-root-bucket", diagnostic)

    def test_destroy_policy_requires_confirm_flag_and_maps_to_two(self) -> None:
        """Refuse DESTROY configuration unless explicitly acknowledged."""
        text = self.config_path.read_text().replace(
            "removal_policy = RETAIN", "removal_policy = DESTROY", 1
        )
        self.config_path.write_text(text)
        args = build_parser().parse_args(self.arguments())
        with patch("sys.stderr") as stderr:
            self.assertEqual(execute(args), EXIT_INVALID_ARGUMENTS)
        diagnostic = "".join(call.args[0] for call in stderr.write.call_args_list)
        self.assertIn("[storage] removal_policy", diagnostic)

    @patch("cromwell_cdk.cli.shutil.which", return_value=None)
    def test_missing_cdk_cli_maps_to_exit_four(self, _which: Mock) -> None:
        """Return prerequisite exit code when CDK is unavailable."""
        args = build_parser().parse_args(self.arguments("--dry-run"))
        with patch("sys.stderr") as stderr:
            self.assertEqual(execute(args), EXIT_PREREQUISITE)
        diagnostic = "".join(call.args[0] for call in stderr.write.call_args_list)
        self.assertIn("cdk", diagnostic)

    @patch("cromwell_cdk.cli.subprocess.run")
    @patch("cromwell_cdk.cli.shutil.which", return_value="/usr/bin/cdk")
    def test_subprocess_receives_argument_list_without_shell(
        self, _which: Mock, run: Mock
    ) -> None:
        """Pass paths and values as argv tokens and suppress lookups for dry-run."""
        run.return_value = Mock(returncode=0)
        args = build_parser().parse_args(
            self.arguments("--dry-run", "--profile", "operator")
        )
        self.assertEqual(execute(args), EXIT_SUCCESS)
        command = run.call_args.args[0]
        self.assertIsInstance(command, list)
        self.assertIn("--context", command)
        self.assertIn(f"deploymentConfig={self.config_path.resolve()}", command)
        self.assertIn("cromwellRootBucket=example-root-bucket", command)
        self.assertIn("--lookups", command)
        self.assertIn("false", command)
        self.assertIn("--profile", command)
        self.assertIn("--region", command)
        self.assertIn("--app", command)
        self.assertTrue(any("python app.py" in argument for argument in command))
        self.assertTrue(
            any(argument.startswith("cromwellRootBucket=") for argument in command)
        )
        self.assertTrue(
            any(argument.startswith("deploymentConfig=") for argument in command)
        )
        self.assertNotIn("shell", run.call_args.kwargs)

    @patch("cromwell_cdk.cli.subprocess.run")
    @patch("cromwell_cdk.cli.shutil.which", return_value="/usr/bin/cdk")
    def test_cdk_nonzero_status_maps_to_exit_five(
        self, _which: Mock, run: Mock
    ) -> None:
        """Preserve failed CDK operations as exit code 5."""
        run.return_value = Mock(returncode=42)
        args = build_parser().parse_args(self.arguments())
        self.assertEqual(execute(args), EXIT_OPERATION)

    @patch("cromwell_cdk.cli.subprocess.run")
    @patch("cromwell_cdk.cli.shutil.which", return_value="/usr/bin/cdk")
    def test_missing_vpc_prerequisite_reported_by_cdk_maps_to_exit_four(
        self, _which: Mock, run: Mock
    ) -> None:
        """Map synthesis-time VPC/subnet prerequisite errors to exit code 4."""
        run.return_value = Mock(
            returncode=1,
            stderr="PrereqError: Configured private subnet(s) not found in VPC",
            stdout="",
        )
        args = build_parser().parse_args(self.arguments())
        with patch("sys.stderr") as stderr:
            self.assertEqual(execute(args), EXIT_PREREQUISITE)
        self.assertTrue(stderr.write.called)

    @patch("cromwell_cdk.cli.subprocess.run")
    @patch("cromwell_cdk.cli.shutil.which", return_value="/usr/bin/cdk")
    def test_uncached_dry_run_vpc_lookup_maps_to_exit_four(
        self, _which: Mock, run: Mock
    ) -> None:
        """Explain that dry-run cannot perform uncached AWS context lookups."""
        run.return_value = Mock(
            returncode=1,
            stderr="Cannot retrieve value from context provider vpc-provider",
            stdout="",
        )
        args = build_parser().parse_args(self.arguments("--dry-run"))
        with patch("sys.stderr") as stderr:
            self.assertEqual(execute(args), EXIT_PREREQUISITE)
        diagnostic = "".join(call.args[0] for call in stderr.write.call_args_list)
        self.assertIn("dry-run skipped AWS subnet/AZ checks", diagnostic)

    @patch("cromwell_cdk.cli.subprocess.run")
    @patch("cromwell_cdk.cli.shutil.which", return_value="/usr/bin/cdk")
    def test_cdk_error_diagnostic_is_one_line(self, _which: Mock, run: Mock) -> None:
        """Collapse CDK multiline errors to the required one-line diagnostic."""
        run.return_value = Mock(
            returncode=42,
            stderr="first failure\nsecond failure",
            stdout="",
        )
        args = build_parser().parse_args(self.arguments())
        with patch("cromwell_cdk.cli.logging.error") as log_error:
            self.assertEqual(execute(args), EXIT_OPERATION)
        message = log_error.call_args.args[1]
        self.assertEqual(len(message.splitlines()), 1)
        self.assertIn("first failure second failure", message)

    @patch("cromwell_cdk.cli.subprocess.run")
    @patch("cromwell_cdk.cli.shutil.which", return_value="/usr/bin/cdk")
    def test_empty_app_synth_failure_maps_to_exit_five(
        self, _which: Mock, run: Mock
    ) -> None:
        """Treat CDK's no-stack diagnostic as a failed synth operation."""
        run.return_value = Mock(
            returncode=1,
            stderr="This app contains no stacks",
            stdout="",
        )
        args = build_parser().parse_args(self.arguments("--dry-run"))
        with patch("cromwell_cdk.cli.logging.error") as log_error:
            self.assertEqual(execute(args), EXIT_OPERATION)
        log_error.assert_called_once()
        self.assertTrue(run.call_args.kwargs["capture_output"])

    @patch("cromwell_cdk.cli.subprocess.run")
    @patch("cromwell_cdk.cli.shutil.which", return_value="/usr/bin/cdk")
    def test_deploy_failure_keeps_cdk_output_visible(
        self, _which: Mock, run: Mock
    ) -> None:
        """Do not capture deploy output or approval prompts from the operator."""
        run.return_value = Mock(returncode=42)
        args = build_parser().parse_args(self.arguments("--action", "deploy"))
        with patch("cromwell_cdk.cli.logging.error"):
            self.assertEqual(execute(args), EXIT_OPERATION)
        self.assertFalse(run.call_args.kwargs["capture_output"])

    def test_main_initializes_logging_and_returns_exit_code(self) -> None:
        """Initialize logging in main and return the execute result."""
        with (
            patch("cromwell_cdk.cli.logging.basicConfig") as basic_config,
            patch("cromwell_cdk.cli.execute", return_value=EXIT_SUCCESS),
        ):
            self.assertEqual(main(self.arguments()), EXIT_SUCCESS)
        basic_config.assert_called_once()

    def test_main_rejects_invalid_config_before_logging_setup(self) -> None:
        """Parse and validate the config file before initializing logging."""
        self.config_path.write_text("[deployment]\nnamespace = INVALID\n")
        with (
            patch("cromwell_cdk.cli.logging.basicConfig") as basic_config,
            patch("sys.stderr"),
        ):
            self.assertEqual(main(self.arguments()), EXIT_CONFIGURATION)
        basic_config.assert_not_called()
