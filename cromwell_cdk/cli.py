"""Command-line interface for validating and operating the Cromwell CDK app."""

from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from cromwell_cdk.config import DeploymentConfig, load_config, validate_config
from cromwell_cdk.errors import ConfigError, DeployError, PrereqError


EXIT_SUCCESS = 0
EXIT_INVALID_ARGUMENTS = 2
EXIT_CONFIGURATION = 3
EXIT_PREREQUISITE = 4
EXIT_OPERATION = 5


def build_parser() -> argparse.ArgumentParser:
    """Create the deployment CLI argument parser.

    Returns:
        Configured argument parser.

    Raises:
        None: Parser configuration does not deliberately raise.
    """
    parser = _CliArgumentParser(
        prog="deploy-cromwell",
        description="Validate, synthesize, deploy, or destroy the Cromwell AWS platform.",
    )
    parser.add_argument("--region", required=True, help="Target AWS region")
    parser.add_argument("--profile", help="AWS named profile")
    parser.add_argument(
        "--cromwell-root-bucket", required=True, help="Primary Cromwell S3 bucket name"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configuration.ini"),
        help="Configuration file (default: ./configuration.ini)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate configuration and synthesize without AWS mutation",
    )
    parser.add_argument(
        "--confirm-destroy-data",
        action="store_true",
        help="Acknowledge data deletion when a DESTROY removal policy is configured",
    )
    parser.add_argument(
        "--action",
        choices=("synth", "deploy", "destroy"),
        default="synth",
        help="CDK operation (default: synth)",
    )
    return parser


class _CliArgumentParser(argparse.ArgumentParser):
    """Argument parser that emits contract-compliant exit codes and diagnostics."""

    def error(self, message: str) -> None:
        """Print one actionable parser diagnostic and exit with code 2.

        Args:
            message: Parser-generated description of the invalid input.

        Raises:
            SystemExit: Always, with the invalid-arguments exit code.
        """
        self.print_usage(sys.stderr)
        self.exit(EXIT_INVALID_ARGUMENTS, f"{self.prog}: error: {message}\n")

    def exit(self, status: int = 0, message: str | None = None) -> None:
        """Exit with the parser status while routing diagnostics to stderr.

        Args:
            status: Process exit status.
            message: Optional parser message.

        Raises:
            SystemExit: Always, with the supplied status.
        """
        if message:
            print(message, file=sys.stderr if status else sys.stdout, end="")
        raise SystemExit(status)


def _validate_destroy_confirmation(config: DeploymentConfig, confirmed: bool) -> None:
    """Require explicit consent before any action with destructive policies.

    Args:
        config: Validated deployment configuration.
        confirmed: Whether the operator supplied the confirmation flag.

    Raises:
        ConfigError: If a DESTROY policy is configured without confirmation.
    """
    destructive = (
        (
            "[storage] removal_policy",
            config.get("storage", "removal_policy") == "DESTROY",
        ),
        (
            "[artifacts] artifact_bucket_removal_policy",
            config.get("artifacts", "artifact_bucket_removal_policy") == "DESTROY",
        ),
        (
            "[database] removal_policy",
            config.get("database", "removal_policy") == "DESTROY",
        ),
    )
    if not confirmed:
        for key, is_destructive in destructive:
            if is_destructive:
                raise ConfigError(
                    f"Invalid {key}: DESTROY requires --confirm-destroy-data"
                )


def _run_cdk(args: argparse.Namespace, action: str) -> None:
    """Run a CDK operation with safely separated arguments.

    Args:
        args: Parsed CLI options.
        action: One of synth, deploy, or destroy.

    Raises:
        PrereqError: If the CDK executable is unavailable.
        DeployError: If the CDK process exits unsuccessfully.
    """
    executable = shutil.which("cdk")
    if executable is None:
        raise PrereqError(
            "Required prerequisite missing: AWS CDK CLI 'cdk' not found in PATH"
        )

    uv_executable = shutil.which("uv")
    python_command = f"{uv_executable} run python" if uv_executable else sys.executable
    command = [executable, action]
    command.extend(["--app", f"{python_command} app.py"])
    if args.region:
        command.extend(["--region", args.region])
    if args.profile:
        command.extend(["--profile", args.profile])
    command.extend(["--context", f"cromwellRootBucket={args.cromwell_root_bucket}"])
    config_path = Path(args.config).resolve()
    command.extend(["--context", f"deploymentConfig={config_path}"])
    if args.dry_run:
        command.extend(["--lookups", "false"])

    try:
        project_root = Path(__file__).resolve().parent.parent
        completed = subprocess.run(
            command,
            check=False,
            cwd=project_root,
            text=True,
            capture_output=action == "synth",
        )
    except OSError as exc:
        raise PrereqError(f"Unable to start AWS CDK CLI: {exc}") from exc
    if completed.returncode != 0:
        stderr = getattr(completed, "stderr", None)
        stdout = getattr(completed, "stdout", None)
        stderr_text = stderr if isinstance(stderr, str) else ""
        stdout_text = stdout if isinstance(stdout, str) else ""
        details = stderr_text or stdout_text
        details = details.strip()
        if action == "synth" and "PrereqError:" in details:
            diagnostic = " ".join(details.splitlines())
            raise PrereqError(diagnostic)
        if (
            action == "synth"
            and "Cannot retrieve value from context provider vpc-provider" in details
        ):
            raise PrereqError(
                "Required prerequisite missing: VPC lookup context unavailable; "
                "dry-run skipped AWS subnet/AZ checks"
            )
        suffix = f": {details}" if details else ""
        raise DeployError(
            f"CDK {action} failed with exit status {completed.returncode}{suffix}"
        )


def execute(args: argparse.Namespace) -> int:
    """Validate inputs and execute the selected CDK workflow.

    Args:
        args: Parsed CLI options.

    Returns:
        Process exit code using the public CLI mapping.

    Raises:
        None: Expected configuration and process errors are mapped to exit codes.
    """
    try:
        if not args.cromwell_root_bucket.strip():
            print(
                "Invalid --cromwell-root-bucket: value cannot be empty", file=sys.stderr
            )
            return EXIT_INVALID_ARGUMENTS
        config = getattr(args, "deployment_config", None) or load_config(args.config)
        validate_config(config)
        if args.dry_run:
            logging.info("Stage: configuration validation and CDK synth")
            logging.info(
                "AWS-aware subnet/AZ checks: skipped unless lookup context is cached"
            )
        try:
            _validate_destroy_confirmation(config, args.confirm_destroy_data)
        except ConfigError as exc:
            print(str(exc), file=sys.stderr)
            return EXIT_INVALID_ARGUMENTS
        action = "synth" if args.dry_run else args.action
        _run_cdk(args, action)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_CONFIGURATION
    except PrereqError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_PREREQUISITE
    except DeployError as exc:
        diagnostic = " ".join(str(exc).splitlines())
        logging.error("CDK operation failed: %s", diagnostic)
        return EXIT_OPERATION
    return EXIT_SUCCESS


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments, initialize logging once, and run the selected action.

    Args:
        argv: Optional argument sequence; defaults to process arguments.

    Returns:
        Process exit code. Console-script callers exit with this value.

    Raises:
        SystemExit: If argparse detects invalid or incomplete arguments.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.cromwell_root_bucket.strip():
        print("Invalid --cromwell-root-bucket: value cannot be empty", file=sys.stderr)
        return EXIT_INVALID_ARGUMENTS
    try:
        args.deployment_config = load_config(args.config)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_CONFIGURATION
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    return execute(args)


def entrypoint() -> None:
    """Run the console script and exit using its mapped status code.

    Raises:
        SystemExit: With the CLI's mapped process exit status.
    """
    raise SystemExit(main())


if __name__ == "__main__":
    raise SystemExit(main())
