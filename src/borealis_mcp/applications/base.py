"""Base application interface for Borealis MCP."""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from fastmcp import FastMCP

from borealis_mcp.config.system import SystemConfig


class ApplicationBase(ABC):
    """
    Base class for all Borealis applications.

    Applications are plugins that add domain-specific tools and resources
    to the MCP server. Each application can provide:
    - Tools for generating submit scripts
    - Tools for application-specific operations
    - Resources with application documentation
    - Prompts for guided workflows
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Unique identifier for this application.

        Returns:
            Application name (e.g., "hello_world", "pytorch")
        """
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """
        Human-readable description of the application.

        Returns:
            Description string
        """
        ...

    def supports_system(self, system_config: SystemConfig) -> bool:
        """
        Check if this application supports the given system.

        Override this method to restrict application to specific systems.
        Default implementation returns True (supports all systems).

        Args:
            system_config: System configuration to check

        Returns:
            True if application supports this system
        """
        return True

    def get_system_settings(self, system_config: SystemConfig) -> Dict[str, Any]:
        """
        Get system-specific settings for this application.

        Override to provide system-adaptive configuration.

        Args:
            system_config: Current system configuration

        Returns:
            Dictionary of settings
        """
        return {}

    @abstractmethod
    def register_tools(
        self,
        mcp: FastMCP,
        system_config: SystemConfig,
        app_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Register application-specific MCP tools.

        This is the main extension point. Implement this method to add
        tools to the MCP server.

        Args:
            mcp: FastMCP server instance
            system_config: Current system configuration
            app_config: Optional application-specific configuration from YAML
        """
        ...

    def register_resources(
        self,
        mcp: FastMCP,
        system_config: SystemConfig,
        app_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Register application-specific MCP resources.

        Override to add resources (optional).

        Args:
            mcp: FastMCP server instance
            system_config: Current system configuration
            app_config: Optional application-specific configuration
        """
        pass

    def register_prompts(
        self,
        mcp: FastMCP,
        system_config: SystemConfig,
        app_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Register application-specific MCP prompts.

        Override to add prompts (optional).

        Args:
            mcp: FastMCP server instance
            system_config: Current system configuration
            app_config: Optional application-specific configuration
        """
        pass

    def register_all(
        self,
        mcp: FastMCP,
        system_config: SystemConfig,
        app_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Register all application components (tools, resources, prompts).

        This is called by the registry to register the application.

        Args:
            mcp: FastMCP server instance
            system_config: Current system configuration
            app_config: Optional application-specific configuration
        """
        self.register_tools(mcp, system_config, app_config)
        self.register_resources(mcp, system_config, app_config)
        self.register_prompts(mcp, system_config, app_config)
