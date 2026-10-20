"""Domain exceptions raised by the Cromwell CDK application."""


class ConfigError(ValueError):
    """Raised when deployment configuration is missing or invalid."""


class PrereqError(RuntimeError):
    """Raised when a required local or deployment prerequisite is unavailable."""


class DeployError(RuntimeError):
    """Raised when a deployment operation fails."""
