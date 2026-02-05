"""Custom exception classes for Borealis MCP."""

from typing import List, Optional


class BorealisError(Exception):
    """Base exception for Borealis MCP."""

    pass


class ConfigurationError(BorealisError):
    """Configuration error (missing files, invalid YAML, etc.)."""

    pass


class ValidationError(BorealisError):
    """Input validation error."""

    pass


class AccountNotConfiguredError(ValidationError):
    """
    PBS account not configured.

    Raised when PBS_ACCOUNT environment variable is not set
    and no account is provided explicitly.
    """

    def __init__(self, message: Optional[str] = None):
        default_message = (
            "PBS account not configured. "
            "Set the PBS_ACCOUNT environment variable to your project allocation name. "
            "Example: export PBS_ACCOUNT=myproject"
        )
        super().__init__(message or default_message)


class PBSConnectionError(BorealisError):
    """
    PBS connection failed.

    Raised when unable to connect to PBS server.
    """

    def __init__(
        self, server: str, system_name: str, original_error: Optional[str] = None
    ):
        message = (
            f"Failed to connect to PBS server '{server}'. "
            f"Ensure you are on a {system_name} login node with PBS access. "
        )
        if original_error:
            message += f"Details: {original_error}"
        super().__init__(message)
        self.server = server
        self.system_name = system_name


class PBSOperationError(BorealisError):
    """PBS operation failed."""

    def __init__(self, operation: str, message: str, errno: Optional[int] = None):
        super().__init__(f"PBS {operation} failed: {message}")
        self.operation = operation
        self.errno = errno


class ApplicationError(BorealisError):
    """Application-specific error."""

    pass


class SystemNotFoundError(ConfigurationError):
    """
    System configuration not found.

    Raised when a requested system has no YAML configuration.
    """

    def __init__(
        self, system_name: str, available_systems: Optional[List[str]] = None
    ):
        message = f"System '{system_name}' not found."
        if available_systems:
            message += f" Available systems: {', '.join(available_systems)}"
        super().__init__(message)
        self.system_name = system_name
        self.available_systems = available_systems or []
