"""Application registry for Borealis MCP."""

import importlib
import pkgutil
from pathlib import Path
from typing import Dict, List, Optional, Type

from fastmcp import FastMCP

from borealis_mcp.applications.base import ApplicationBase
from borealis_mcp.config.system import SystemConfig, SystemConfigLoader
from borealis_mcp.core.workspace import WorkspaceManager
from borealis_mcp.utils.logging import get_logger

logger = get_logger("registry")


class ApplicationRegistry:
    """
    Registry for discovering and managing Borealis applications.

    Applications are auto-discovered from the applications package.
    Each application module must define an `Application` class that
    inherits from `ApplicationBase`.
    """

    def __init__(self):
        self._applications: Dict[str, ApplicationBase] = {}

    def discover_applications(self) -> None:
        """
        Auto-discover applications in the applications package.

        Looks for modules in borealis_mcp.applications that have an
        `Application` class inheriting from `ApplicationBase`.
        """
        import borealis_mcp.applications as apps_package

        package_path = Path(apps_package.__file__).parent

        for module_info in pkgutil.iter_modules([str(package_path)]):
            if module_info.ispkg:  # Only look at subpackages
                module_name = module_info.name
                try:
                    # Import the subpackage
                    module = importlib.import_module(
                        f"borealis_mcp.applications.{module_name}"
                    )

                    # Look for Application class
                    if hasattr(module, "Application"):
                        app_class = getattr(module, "Application")
                        if (
                            isinstance(app_class, type)
                            and issubclass(app_class, ApplicationBase)
                            and app_class is not ApplicationBase
                        ):
                            app_instance = app_class()
                            self._applications[app_instance.name] = app_instance
                            logger.debug(f"Discovered application: {app_instance.name}")

                except Exception as e:
                    logger.warning(f"Failed to load application {module_name}: {e}")

        logger.info(
            f"Discovered {len(self._applications)} applications: "
            f"{list(self._applications.keys())}"
        )

    def register_application(self, app: ApplicationBase) -> None:
        """
        Manually register an application.

        Args:
            app: Application instance to register
        """
        self._applications[app.name] = app
        logger.debug(f"Registered application: {app.name}")

    def get_application(self, name: str) -> Optional[ApplicationBase]:
        """
        Get an application by name.

        Args:
            name: Application name

        Returns:
            Application instance or None if not found
        """
        return self._applications.get(name)

    def list_applications(self) -> List[str]:
        """
        List all registered application names.

        Returns:
            List of application names
        """
        return list(self._applications.keys())

    def register_all(
        self,
        mcp: FastMCP,
        system_config: SystemConfig,
        config_loader: SystemConfigLoader,
        workspace_manager: Optional[WorkspaceManager] = None,
    ) -> None:
        """
        Register all applications with the MCP server.

        Args:
            mcp: FastMCP server instance
            system_config: Current system configuration
            config_loader: Configuration loader for app-specific configs
            workspace_manager: Workspace manager for job workspaces
        """
        for name, app in self._applications.items():
            # Check if application supports this system
            if not app.supports_system(system_config):
                logger.info(
                    f"Skipping {name}: does not support {system_config.name}"
                )
                continue

            # Load application-specific configuration
            app_config = config_loader.load_app_config(name, system_config.name)

            try:
                app.register_all(mcp, system_config, app_config, workspace_manager)
                logger.info(f"Registered application: {name}")
            except Exception as e:
                logger.error(f"Failed to register application {name}: {e}")

    def get_application_info(self) -> List[Dict]:
        """
        Get information about all registered applications.

        Returns:
            List of dictionaries with application info
        """
        return [
            {"name": app.name, "description": app.description}
            for app in self._applications.values()
        ]
