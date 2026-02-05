"""System configuration classes for Borealis MCP."""

import os
import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from borealis_mcp.config.constants import (
    ENV_BOREALIS_CONFIG_DIR,
    ENV_BOREALIS_SYSTEM,
)


@dataclass
class QueueConfig:
    """Configuration for a PBS queue."""

    name: str
    max_walltime: str
    max_nodes: int
    node_types: List[str] = field(default_factory=list)
    filesystems: List[str] = field(default_factory=list)
    description: str = ""
    default_place: str = "scatter"
    priority: int = 0

    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> "QueueConfig":
        """Create QueueConfig from dictionary."""
        return cls(
            name=name,
            max_walltime=data.get("max_walltime", "01:00:00"),
            max_nodes=data.get("max_nodes", 1),
            node_types=data.get("node_types", []),
            filesystems=data.get("filesystems", []),
            description=data.get("description", ""),
            default_place=data.get("default_place", "scatter"),
            priority=data.get("priority", 0),
        )


@dataclass
class SystemConfig:
    """Configuration for an HPC system."""

    # Identity
    name: str
    display_name: str
    facility: str
    pbs_server: str

    # Hardware
    total_nodes: int
    cores_per_node: int
    gpus_per_node: int
    gpu_type: str
    memory_per_node: int  # GB
    memory_type: str
    cpu_model: str
    interconnect: str

    # Queues
    queues: Dict[str, QueueConfig] = field(default_factory=dict)

    # Filesystems
    filesystems: Dict[str, str] = field(default_factory=dict)
    default_filesystems: List[str] = field(default_factory=list)

    # Software
    recommended_modules: List[str] = field(default_factory=list)

    # Custom settings (application-specific)
    custom_settings: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SystemConfig":
        """Create SystemConfig from dictionary (parsed YAML)."""
        hardware = data.get("hardware", {})

        # Parse queues
        queues = {}
        for queue_name, queue_data in data.get("queues", {}).items():
            queues[queue_name] = QueueConfig.from_dict(queue_name, queue_data)

        return cls(
            name=data.get("name", "unknown"),
            display_name=data.get("display_name", data.get("name", "Unknown")),
            facility=data.get("facility", ""),
            pbs_server=data.get("pbs_server", ""),
            total_nodes=hardware.get("total_nodes", 0),
            cores_per_node=hardware.get("cores_per_node", 1),
            gpus_per_node=hardware.get("gpus_per_node", 0),
            gpu_type=hardware.get("gpu_type", ""),
            memory_per_node=hardware.get("memory_per_node", 0),
            memory_type=hardware.get("memory_type", ""),
            cpu_model=hardware.get("cpu_model", ""),
            interconnect=hardware.get("interconnect", ""),
            queues=queues,
            filesystems=data.get("filesystems", {}),
            default_filesystems=data.get("default_filesystems", []),
            recommended_modules=data.get("recommended_modules", []),
            custom_settings=data.get("custom_settings", {}),
        )

    def get_queue(self, queue_name: str) -> Optional[QueueConfig]:
        """Get queue configuration by name."""
        return self.queues.get(queue_name)

    def get_default_queue(self) -> Optional[QueueConfig]:
        """Get the default queue (debug if available, otherwise first queue)."""
        if "debug" in self.queues:
            return self.queues["debug"]
        if self.queues:
            return next(iter(self.queues.values()))
        return None

    def get_filesystem_path(self, name: str) -> Optional[str]:
        """Get filesystem path by name."""
        return self.filesystems.get(name)


class SystemConfigLoader:
    """Loader for system configurations from YAML files."""

    def __init__(self, config_dir: Optional[Path] = None):
        """
        Initialize the config loader.

        Args:
            config_dir: Path to config directory. If not provided, uses
                        BOREALIS_CONFIG_DIR env var or defaults to ./config
        """
        if config_dir:
            self.config_dir = Path(config_dir)
        elif os.environ.get(ENV_BOREALIS_CONFIG_DIR):
            self.config_dir = Path(os.environ[ENV_BOREALIS_CONFIG_DIR])
        else:
            # Default to config/ relative to the package or cwd
            self.config_dir = Path.cwd() / "config"

        self.systems_dir = self.config_dir / "systems"
        self._current_system: Optional[SystemConfig] = None
        self._loaded_systems: Dict[str, SystemConfig] = {}

    def discover_systems(self) -> Dict[str, Path]:
        """Discover available system configuration files.

        Returns:
            Dictionary mapping system names to their YAML file paths.
        """
        systems = {}
        if self.systems_dir.exists():
            for yaml_file in self.systems_dir.glob("*.yaml"):
                if not yaml_file.name.startswith("local"):
                    system_name = yaml_file.stem
                    systems[system_name] = yaml_file
        return systems

    def list_available_systems(self) -> List[str]:
        """List names of available system configurations.

        Returns:
            List of system names.
        """
        return list(self.discover_systems().keys())

    def load_system(self, name: str) -> SystemConfig:
        """Load a system configuration by name.

        Args:
            name: System name (e.g., 'aurora', 'polaris')

        Returns:
            SystemConfig object

        Raises:
            FileNotFoundError: If system config file doesn't exist
            yaml.YAMLError: If YAML parsing fails
        """
        # Return cached if available
        if name in self._loaded_systems:
            return self._loaded_systems[name]

        # Find and load the config file
        systems = self.discover_systems()
        if name not in systems:
            available = self.list_available_systems()
            raise FileNotFoundError(
                f"System '{name}' not found. Available systems: {available}"
            )

        config_path = systems[name]
        with open(config_path) as f:
            data = yaml.safe_load(f)

        config = SystemConfig.from_dict(data)
        self._loaded_systems[name] = config
        return config

    def set_current_system(self, name: str) -> None:
        """Set the current active system.

        Args:
            name: System name to set as current
        """
        self._current_system = self.load_system(name)

    def get_current_system(self) -> SystemConfig:
        """Get the current active system configuration.

        Returns:
            Current SystemConfig

        Raises:
            RuntimeError: If no system has been set
        """
        if self._current_system is None:
            raise RuntimeError(
                "No system configured. Call set_current_system() first or set "
                f"{ENV_BOREALIS_SYSTEM} environment variable."
            )
        return self._current_system

    def load_server_config(self) -> Dict[str, Any]:
        """Load the main borealis.yaml server configuration.

        Returns:
            Dictionary with server configuration
        """
        config_path = self.config_dir / "borealis.yaml"
        if config_path.exists():
            with open(config_path) as f:
                return yaml.safe_load(f) or {}
        return {}

    def load_app_config(
        self, app_name: str, system_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """Load application-specific configuration.

        Looks for config in order:
        1. config/applications/{app_name}/{system_name}.yaml
        2. config/applications/{app_name}/default.yaml

        Args:
            app_name: Application name (e.g., 'hello_world')
            system_name: System name (e.g., 'aurora'). Uses current if not provided.

        Returns:
            Dictionary with application configuration
        """
        if system_name is None and self._current_system:
            system_name = self._current_system.name

        app_config_dir = self.config_dir / "applications" / app_name

        # Try system-specific config first
        if system_name:
            system_config = app_config_dir / f"{system_name}.yaml"
            if system_config.exists():
                with open(system_config) as f:
                    return yaml.safe_load(f) or {}

        # Fall back to default config
        default_config = app_config_dir / "default.yaml"
        if default_config.exists():
            with open(default_config) as f:
                return yaml.safe_load(f) or {}

        return {}

    @staticmethod
    def detect_system_from_hostname() -> Optional[str]:
        """Attempt to detect the current system from hostname.

        Returns:
            System name if detected, None otherwise
        """
        hostname = socket.gethostname().lower()

        if "aurora" in hostname:
            return "aurora"
        elif "polaris" in hostname:
            return "polaris"
        elif "sunspot" in hostname:
            return "sunspot"

        return None
