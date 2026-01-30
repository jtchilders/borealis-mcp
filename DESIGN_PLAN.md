# Borealis MCP - Design Document

**Target System:** Aurora Supercomputer (ALCF)  
**Version:** 0.1  
**Date:** January 30, 2026

## Executive Summary

Borealis MCP is an extensible Model Context Protocol server designed to run on Aurora's login nodes, enabling AI agents to interact with the Aurora supercomputer through a well-organized, application-specific interface. The server bridges AI assistants with PBS job scheduling, application-specific tooling, and system resources.

## Design Philosophy

### Core Principles

1. **Extensibility First**: Modular architecture allowing easy addition of new applications
2. **Clear Separation**: PBS core operations separate from application-specific logic
3. **Multi-System Support**: User-configurable system definitions for Aurora, Polaris, and future systems
4. **Agent-Friendly**: Tools and resources designed for LLM consumption and workflow composition
5. **Safety**: Validation and privilege checking built into all operations

### Key Goals

- Enable agents to submit, monitor, and manage PBS jobs on multiple ALCF systems
- Provide application-specific tools that adapt to different system configurations
- Allow easy addition of new systems via user-defined configuration files
- Allow easy addition of new applications without modifying core PBS logic
- Maintain clean separation between infrastructure (PBS) and applications (ML workloads, simulations, etc.)

## System Architecture

### High-Level Organization

```
borealis-mcp/
├── src/borealis_mcp/
│   ├── server.py                    # Main FastMCP server entry point
│   ├── config/
│   │   ├── __init__.py
│   │   ├── system.py                # SystemConfig class and loader
│   │   └── constants.py             # System-wide constants
│   ├── core/
│   │   ├── __init__.py
│   │   ├── pbs_client.py            # PBS API wrapper integration
│   │   ├── pbs_tools.py             # Core PBS MCP tools
│   │   ├── pbs_resources.py         # Core PBS MCP resources
│   │   └── pbs_prompts.py           # Core PBS workflow prompts
│   ├── applications/
│   │   ├── __init__.py
│   │   ├── base.py                  # Base application interface
│   │   ├── registry.py              # Application registration system
│   │   ├── hello_world/
│   │   │   ├── __init__.py
│   │   │   ├── tools.py
│   │   │   └── templates.py
│   │   └── generic/
│   │       ├── __init__.py
│   │       ├── tools.py
│   │       └── templates.py
│   └── utils/
│       ├── __init__.py
│       ├── validation.py            # Input validation utilities
│       ├── formatting.py            # Output formatting utilities
│       └── errors.py                # Custom exception classes
├── config/                          # User configuration directory
│   ├── borealis.yaml                # Server configuration
│   ├── systems/                     # System definitions (YAML)
│   │   ├── README.md                # Guide for creating system configs
│   │   ├── aurora.yaml              # Aurora configuration
│   │   ├── polaris.yaml             # Polaris configuration
│   │   ├── sunspot.yaml             # Sunspot configuration
│   │   └── my_custom_system.yaml    # Example custom system
│   └── applications/                # Application-specific configs (optional)
│       ├── README.md                # Guide for app configs
│       └── hello_world/             # Example: hello_world app configs
│           ├── aurora.yaml          # Aurora-specific settings
│           ├── polaris.yaml         # Polaris-specific settings
│           └── default.yaml         # Fallback settings
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── examples/
│   ├── submit_pytorch_job.py
│   ├── monitor_workflow.py
│   └── multi_stage_pipeline.py
├── docs/
│   ├── getting_started.md
│   ├── adding_applications.md
│   ├── api_reference.md
│   └── aurora_guide.md
├── pyproject.toml
├── requirements.txt
└── README.md
```

## Component Details

### 1. Server Entry Point (`server.py`)

The main FastMCP server that orchestrates all components and manages system configuration.

```python
import os
import sys
import socket
from fastmcp import FastMCP
from pathlib import Path

from borealis_mcp.config.system import SystemConfigLoader
from borealis_mcp.core.pbs_tools import register_pbs_tools
from borealis_mcp.core.pbs_resources import register_pbs_resources
from borealis_mcp.core.pbs_prompts import register_pbs_prompts
from borealis_mcp.applications.registry import ApplicationRegistry

# Initialize MCP server
mcp = FastMCP("Borealis MCP", version="1.0.0")

# Load system configurations
config_loader = SystemConfigLoader()

# Load server config (for default_system, etc.)
server_config = config_loader.load_server_config()

# Determine current system
# Priority: 1) BOREALIS_SYSTEM env var, 2) borealis.yaml default, 3) auto-detect, 4) first available
current_system_name = os.environ.get('BOREALIS_SYSTEM')
if not current_system_name:
    current_system_name = server_config.get('default_system')
if not current_system_name:
    # Try to auto-detect based on hostname
    hostname = socket.gethostname()
    if 'aurora' in hostname:
        current_system_name = 'aurora'
    elif 'polaris' in hostname:
        current_system_name = 'polaris'
    elif 'sunspot' in hostname:
        current_system_name = 'sunspot'
if not current_system_name:
    # Default to first available system
    available = config_loader.list_available_systems()
    if available:
        current_system_name = available[0]
    else:
        raise RuntimeError("No system configurations found in config/systems/")

# Load and set current system
config_loader.set_current_system(current_system_name)
current_system = config_loader.get_current_system()

print(f"Borealis MCP initialized for {current_system.display_name}", file=sys.stderr)
print(f"Available systems: {', '.join(config_loader.list_available_systems())}", 
      file=sys.stderr)

# Register core PBS capabilities (pass system config)
register_pbs_tools(mcp, current_system)
register_pbs_resources(mcp, current_system, config_loader)
register_pbs_prompts(mcp, current_system)

# Auto-discover and register applications (pass system config and loader)
registry = ApplicationRegistry()
registry.discover_applications()
registry.register_all(mcp, current_system, config_loader)

if __name__ == "__main__":
    mcp.run(transport="stdio")
```

**Key Features:**
- Automatic system detection based on hostname
- Override via `BOREALIS_SYSTEM` environment variable
- System config passed to all components
- Lists available systems on startup
- Support for user-defined system configurations

### 2. Configuration System (`config/`)

System configuration with YAML-based system definitions.

**Architecture Decision**: All system definitions live in YAML files under `config/systems/`. The `config/system.py` module provides the `SystemConfig` dataclass and `SystemConfigLoader` to read these YAML files. This eliminates redundancy and makes it trivial to add new systems—just drop in a YAML file. No Python code changes needed!

#### `system.py` - System Configuration and Loader
```python
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from pathlib import Path
import yaml
import os

from borealis_mcp.utils.errors import ConfigurationError

@dataclass
class QueueConfig:
    """Configuration for a PBS queue"""
    name: str
    max_walltime: str
    max_nodes: int
    node_types: List[str]
    filesystems: List[str]
    description: str
    default_place: str = "scatter"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for passing to applications"""
        return {
            'name': self.name,
            'max_walltime': self.max_walltime,
            'max_nodes': self.max_nodes,
            'node_types': self.node_types,
            'filesystems': self.filesystems,
            'description': self.description,
            'default_place': self.default_place
        }

@dataclass
class SystemConfig:
    """Configuration for an HPC system"""
    
    # Identification
    name: str
    display_name: str
    facility: str = "ALCF"
    
    # PBS Server
    pbs_server: str
    
    # Hardware specifications
    total_nodes: int
    cores_per_node: int
    gpus_per_node: int
    gpu_type: str
    memory_per_node: int  # GB
    memory_type: str
    
    # Node architecture
    cpu_model: str
    interconnect: str
    
    # Queues
    queues: Dict[str, QueueConfig] = field(default_factory=dict)
    
    # Filesystems
    filesystems: Dict[str, str] = field(default_factory=dict)
    default_filesystems: List[str] = field(default_factory=list)
    
    # Environment
    recommended_modules: List[str] = field(default_factory=list)
    module_system: str = "lmod"
    
    # System-specific settings
    custom_settings: Dict[str, Any] = field(default_factory=dict)
    
    # Application config overrides (optional)
    application_configs: Dict[str, str] = field(default_factory=dict)
    
    def get_queue(self, queue_name: str) -> Optional[QueueConfig]:
        """Get queue configuration by name"""
        return self.queues.get(queue_name)
    
    def get_default_queue(self) -> Optional[QueueConfig]:
        """Get the default queue (usually 'debug' or first defined)"""
        if 'debug' in self.queues:
            return self.queues['debug']
        return next(iter(self.queues.values())) if self.queues else None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for passing to applications"""
        return {
            'name': self.name,
            'display_name': self.display_name,
            'facility': self.facility,
            'pbs_server': self.pbs_server,
            'hardware': {
                'total_nodes': self.total_nodes,
                'cores_per_node': self.cores_per_node,
                'gpus_per_node': self.gpus_per_node,
                'gpu_type': self.gpu_type,
                'memory_per_node': self.memory_per_node,
                'memory_type': self.memory_type,
                'cpu_model': self.cpu_model,
                'interconnect': self.interconnect
            },
            'queues': {name: q.to_dict() for name, q in self.queues.items()},
            'filesystems': self.filesystems,
            'default_filesystems': self.default_filesystems,
            'recommended_modules': self.recommended_modules,
            'module_system': self.module_system,
            'custom_settings': self.custom_settings,
            'application_configs': self.application_configs
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SystemConfig':
        """Create SystemConfig from dictionary (e.g., from YAML)"""
        # Extract hardware nested dict
        hardware = data.get('hardware', {})
        
        # Convert queue dicts to QueueConfig objects
        queues = {}
        for name, q_data in data.get('queues', {}).items():
            queues[name] = QueueConfig(
                name=name,
                max_walltime=q_data['max_walltime'],
                max_nodes=q_data['max_nodes'],
                node_types=q_data.get('node_types', []),
                filesystems=q_data.get('filesystems', []),
                description=q_data.get('description', ''),
                default_place=q_data.get('default_place', 'scatter')
            )
        
        return cls(
            name=data['name'],
            display_name=data.get('display_name', data['name']),
            facility=data.get('facility', 'ALCF'),
            pbs_server=data['pbs_server'],
            total_nodes=hardware['total_nodes'],
            cores_per_node=hardware['cores_per_node'],
            gpus_per_node=hardware.get('gpus_per_node', 0),
            gpu_type=hardware.get('gpu_type', 'None'),
            memory_per_node=hardware['memory_per_node'],
            memory_type=hardware.get('memory_type', 'DDR4'),
            cpu_model=hardware['cpu_model'],
            interconnect=hardware.get('interconnect', 'Unknown'),
            queues=queues,
            filesystems=data.get('filesystems', {}),
            default_filesystems=data.get('default_filesystems', []),
            recommended_modules=data.get('recommended_modules', []),
            module_system=data.get('module_system', 'lmod'),
            custom_settings=data.get('custom_settings', {}),
            application_configs=data.get('application_configs', {})
        )
    
    @classmethod
    def from_yaml(cls, yaml_path: Path) -> 'SystemConfig':
        """Load system config from YAML file"""
        try:
            with open(yaml_path, 'r') as f:
                data = yaml.safe_load(f)
            return cls.from_dict(data)
        except Exception as e:
            raise ConfigurationError(f"Failed to load config from {yaml_path}: {e}")


class SystemConfigLoader:
    """Loads and manages system configurations"""
    
    def __init__(self, config_dir: Optional[Path] = None):
        """
        Initialize the configuration loader.
        
        Args:
            config_dir: Path to config directory (defaults to ./config or BOREALIS_CONFIG_DIR)
        """
        if config_dir is None:
            # Look for config in env variable or current directory
            config_dir = os.environ.get('BOREALIS_CONFIG_DIR', './config')
        self.config_dir = Path(config_dir)
        self.systems_dir = self.config_dir / "systems"
        
        # Cached configurations
        self._configs: Dict[str, SystemConfig] = {}
        self._current_system: Optional[str] = None
    
    def discover_systems(self) -> Dict[str, Path]:
        """Discover all available system YAML files"""
        systems = {}
        if self.systems_dir.exists():
            for yaml_file in self.systems_dir.glob("*.yaml"):
                system_name = yaml_file.stem
                systems[system_name] = yaml_file
        return systems
    
    def load_system(self, system_name: str) -> SystemConfig:
        """
        Load a specific system configuration.
        
        Args:
            system_name: Name of the system (e.g., 'aurora', 'polaris')
            
        Returns:
            SystemConfig object
        """
        # Return cached if available
        if system_name in self._configs:
            return self._configs[system_name]
        
        # Try to load from file
        yaml_path = self.systems_dir / f"{system_name}.yaml"
        if not yaml_path.exists():
            raise ConfigurationError(
                f"System '{system_name}' not found at {yaml_path}. "
                f"Available systems: {', '.join(self.list_available_systems())}"
            )
        
        config = SystemConfig.from_yaml(yaml_path)
        self._configs[system_name] = config
        return config
    
    def set_current_system(self, system_name: str) -> None:
        """Set the current active system"""
        # Ensure the system exists
        self.load_system(system_name)
        self._current_system = system_name
    
    def get_current_system(self) -> Optional[SystemConfig]:
        """Get the current active system configuration"""
        if self._current_system:
            return self._configs.get(self._current_system)
        return None
    
    def list_available_systems(self) -> List[str]:
        """List all available system names"""
        return sorted(self.discover_systems().keys())
    
    def load_application_config(
        self, 
        app_name: str, 
        system_name: str
    ) -> Optional[Dict[str, Any]]:
        """
        Load application-specific configuration for a system.
        
        Lookup priority:
        1. Explicit override in system config (application_configs)
        2. Convention: config/applications/{app_name}/{system_name}.yaml
        3. Fallback: config/applications/{app_name}/default.yaml
        4. None (app works without config)
        
        Args:
            app_name: Name of the application
            system_name: Name of the system
            
        Returns:
            Dictionary of app config or None
        """
        # Get system config to check for overrides
        system_config = self._configs.get(system_name)
        
        # 1. Check for explicit override in system config
        if system_config and app_name in system_config.application_configs:
            config_file = system_config.application_configs[app_name]
            config_path = self.config_dir / "applications" / config_file
            if config_path.exists():
                with open(config_path, 'r') as f:
                    return yaml.safe_load(f)
        
        # 2. Convention-based lookup
        app_dir = self.config_dir / "applications" / app_name
        system_config_path = app_dir / f"{system_name}.yaml"
        if system_config_path.exists():
            with open(system_config_path, 'r') as f:
                return yaml.safe_load(f)
        
        # 3. Default fallback
        default_config_path = app_dir / "default.yaml"
        if default_config_path.exists():
            with open(default_config_path, 'r') as f:
                return yaml.safe_load(f)
        
        # 4. No config needed
        return None
    
    def load_server_config(self) -> Dict[str, Any]:
        """Load the main borealis.yaml server configuration"""
        config_file = self.config_dir / "borealis.yaml"
        if config_file.exists():
            with open(config_file, 'r') as f:
                return yaml.safe_load(f) or {}
        return {}
```

#### `config/borealis.yaml` - Server Configuration
```yaml
# Borealis MCP Server Configuration

# Default system (can be overridden by BOREALIS_SYSTEM env var)
default_system: aurora

# Server settings
server:
  name: "Borealis MCP"
  version: "1.0.0"
  
# Logging
logging:
  level: INFO
  
# Optional: Application-specific settings
applications:
  pytorch:
    default_conda_env: "pytorch_env"
  
  tensorflow:
    default_conda_env: "tf_env"
```

#### `config/systems/aurora.yaml` - Aurora System Definition
```yaml
name: aurora
display_name: "Aurora"
facility: ALCF
pbs_server: aurora-pbs-0001.hostmgmt.cm.aurora.alcf.anl.gov

hardware:
  total_nodes: 10624
  cores_per_node: 104
  gpus_per_node: 12
  gpu_type: "Intel Data Center GPU Max 1550"
  memory_per_node: 512
  memory_type: "HBM2e"
  cpu_model: "Intel Xeon CPU Max 9470C"
  interconnect: "HPE Slingshot 11"

queues:
  debug:
    max_walltime: "01:00:00"
    max_nodes: 16
    node_types: ["x4750"]
    filesystems: ["flare", "home", "eagle"]
    description: "Small interactive debugging jobs"
    default_place: "scatter"
  
  workq:
    max_walltime: "24:00:00"
    max_nodes: 1024
    node_types: ["x4750"]
    filesystems: ["flare", "home", "eagle", "grand"]
    description: "Standard production queue"
    default_place: "scatter"
  
  demand:
    max_walltime: "06:00:00"
    max_nodes: 512
    node_types: ["x4750"]
    filesystems: ["flare", "home", "eagle"]
    description: "On-demand queue for urgent jobs"
    default_place: "scatter"

filesystems:
  flare: "/flare/Aurora_deployment"
  home: "/home"
  eagle: "/eagle"
  grand: "/grand"

default_filesystems: ["flare", "home"]

recommended_modules:
  - "frameworks"
  - "mpich/icc-all-pmix-gpu/20240625"
  - "libfabric/1.15.2.0"

module_system: "lmod"

custom_settings:
  gpu_affinity_mask: "0.0,0.1,1.0,1.1,2.0,2.1,3.0,3.1,4.0,4.1,5.0,5.1"
  ze_enable_pci_id_device_order: 1
  preferred_mpi: "mpich"
  intel_gpu_optimization: true
```

#### `config/systems/polaris.yaml` - Polaris System Definition
```yaml
name: polaris
display_name: "Polaris"
facility: ALCF
pbs_server: polaris-pbs-01.hsn.cm.polaris.alcf.anl.gov

hardware:
  total_nodes: 560
  cores_per_node: 64
  gpus_per_node: 4
  gpu_type: "NVIDIA A100"
  memory_per_node: 512
  memory_type: "DDR4"
  cpu_model: "AMD EPYC 7543P"
  interconnect: "HPE Slingshot 10"

queues:
  debug:
    max_walltime: "01:00:00"
    max_nodes: 8
    node_types: ["polaris"]
    filesystems: ["eagle", "home", "grand"]
    description: "Debug and testing queue"
    default_place: "scatter"
  
  prod:
    max_walltime: "24:00:00"
    max_nodes: 512
    node_types: ["polaris"]
    filesystems: ["eagle", "home", "grand", "theta-fs0"]
    description: "Production queue"
    default_place: "scatter"

filesystems:
  eagle: "/eagle"
  home: "/home"
  grand: "/grand"
  theta-fs0: "/lus/theta-fs0"

default_filesystems: ["eagle", "home"]

recommended_modules:
  - "conda"
  - "cudatoolkit-standalone/11.8.0"
  - "cray-mpich"

module_system: "lmod"

custom_settings:
  cuda_visible_devices: "0,1,2,3"
  preferred_mpi: "cray-mpich"
  nvidia_gpu_optimization: true
  gpu_direct_rdma: true
```

#### `config/systems/sunspot.yaml` - Sunspot System Definition
```yaml
name: sunspot
display_name: "Sunspot"
facility: ALCF
pbs_server: sunspot-pbs-01.sunspot.alcf.anl.gov

hardware:
  total_nodes: 128
  cores_per_node: 104
  gpus_per_node: 12
  gpu_type: "Intel Data Center GPU Max 1100"
  memory_per_node: 512
  memory_type: "HBM2e"
  cpu_model: "Intel Xeon CPU Max 9460"
  interconnect: "HPE Slingshot 11"

queues:
  workq:
    max_walltime: "24:00:00"
    max_nodes: 64
    node_types: ["sunspot"]
    filesystems: ["gila", "home"]
    description: "Standard production queue"
    default_place: "scatter"

filesystems:
  gila: "/gila"
  home: "/home"

default_filesystems: ["gila", "home"]

recommended_modules:
  - "frameworks"

module_system: "lmod"

custom_settings:
  gpu_affinity_mask: "0.0,0.1,1.0,1.1,2.0,2.1,3.0,3.1,4.0,4.1,5.0,5.1"
  ze_enable_pci_id_device_order: 1
  preferred_mpi: "mpich"
  intel_gpu_optimization: true
```

---

### Application Configuration Files

Application configs are optional and provide system-specific settings for applications.

#### `config/applications/hello_world/aurora.yaml`
```yaml
# Hello World configuration for Aurora

# Modules to load
modules:
  - "frameworks"
  - "mpich/icc-all-pmix-gpu/20240625"

# MPI execution settings
mpi:
  command: "mpiexec"
  flags:
    - "--cpu-bind"
    - "depth"

# Environment variables
environment:
  I_MPI_DEBUG: "5"
  FI_CXI_DEFAULT_VNI: "0"

# Default job parameters
defaults:
  walltime: "00:30:00"
  queue: "debug"
```

#### `config/applications/hello_world/polaris.yaml`
```yaml
# Hello World configuration for Polaris

# Modules to load  
modules:
  - "conda"
  - "cray-mpich"

# MPI execution settings
mpi:
  command: "mpiexec"
  flags:
    - "--cpu-bind"
    - "core"

# Environment variables
environment:
  MPICH_GPU_SUPPORT_ENABLED: "1"

# Default job parameters
defaults:
  walltime: "00:30:00"
  queue: "debug"
```

#### `config/applications/hello_world/default.yaml`
```yaml
# Hello World fallback configuration

# Basic modules
modules:
  - "mpi"

# MPI execution settings
mpi:
  command: "mpiexec"
  flags: []

# Environment variables
environment: {}

# Default job parameters
defaults:
  walltime: "00:30:00"
  queue: "debug"
```

#### `config/applications/README.md`
```markdown
# Application Configuration Guide

Application configurations are optional YAML files that provide system-specific settings for applications.

## Directory Structure

\```
config/applications/
  {app_name}/
    {system_name}.yaml  # System-specific config
    default.yaml        # Fallback config (optional)
\```

## Configuration Lookup

When loaded, Borealis MCP looks for configs in this order:

1. Explicit override in system config (optional)
2. Convention: `config/applications/{app_name}/{system_name}.yaml`
3. Fallback: `config/applications/{app_name}/default.yaml`
4. No config (application works without)

## Format

Free-form YAML - each application interprets as needed.

### Example: MPI Application
\```yaml
modules:
  - "frameworks"
  
mpi:
  command: "mpiexec"
  flags: ["--cpu-bind", "depth"]

environment:
  MY_APP_MODE: "optimized"

defaults:
  walltime: "01:00:00"
  queue: "debug"
\```
```

#### `constants.py`
```python
# PBS job states
PBS_JOB_STATES = {
    'Q': 'Queued',
    'R': 'Running',
    'H': 'Held',
    'E': 'Exiting',
    'F': 'Finished',
    'M': 'Moved',
    'W': 'Waiting',
}

# Resource validation patterns
WALLTIME_PATTERN = r'^\d{2}:\d{2}:\d{2}$'
FILESYSTEMS_PATTERN = r'^([a-z]+)(:([a-z]+))*$'

# Tool categories
TOOL_CATEGORIES = {
    "PBS_CORE": "pbs",
    "APPLICATION": "app"
}
```

### 3. Core PBS Layer (`core/`)

Handles all PBS-specific operations using your existing `pbs-python-api`.

#### `pbs_client.py`
```python
from contextlib import contextmanager
from typing import Optional
import os
import sys

# Add pbs-python-api to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../external/pbs-python-api'))
from pbs_api import PBSClient, PBSException

from borealis_mcp.config.system import SystemConfig

@contextmanager
def get_pbs_client(system_config: SystemConfig, server: Optional[str] = None):
    """
    Context manager for PBS client connections.
    
    Args:
        system_config: System configuration object
        server: PBS server hostname (defaults to system config)
    """
    server = server or system_config.pbs_server
    
    with PBSClient(server=server) as client:
        yield client

def validate_pbs_connection(system_config: SystemConfig) -> bool:
    """
    Validate PBS connection is available.
    
    Args:
        system_config: System configuration object
    """
    try:
        with get_pbs_client(system_config) as pbs:
            pbs.stat_server()
        return True
    except PBSException:
        return False
```

#### `pbs_tools.py`
```python
from fastmcp import FastMCP
from typing import Dict, Any, Optional, List
from borealis_mcp.config.system import SystemConfig
from borealis_mcp.core.pbs_client import get_pbs_client
from borealis_mcp.utils.validation import validate_job_id, validate_walltime
from borealis_mcp.utils.formatting import format_job_status, format_queue_summary

def register_pbs_tools(mcp: FastMCP, system_config: SystemConfig):
    """
    Register core PBS tools with the MCP server.
    
    Args:
        mcp: FastMCP server instance
        system_config: Current system configuration
    """
    
    @mcp.tool()
    def submit_pbs_job(
        script_path: str,
        queue: str,
        job_name: str,
        account: str,
        select_spec: str,
        walltime: str,
        filesystems: str,
        additional_attrs: Optional[Dict[str, Any]] = None
    ) -> Dict[str, str]:
        """
        Submit a PBS job to the current system.
        
        Args:
            script_path: Absolute path to job script
            queue: Queue name (debug, workq, etc.)
            job_name: Name for the job
            account: Account/project name
            select_spec: PBS select specification (e.g., "1" for 1 node)
            walltime: Wall time in HH:MM:SS format
            filesystems: Filesystems to mount (e.g., "flare:home")
            additional_attrs: Optional additional PBS attributes
            
        Returns:
            Dictionary with job_id and submission details
        """
        validate_walltime(walltime)
        
        # Validate queue exists in system config
        if queue not in system_config.queues:
            available = ', '.join(system_config.queues.keys())
            raise ValueError(f"Queue '{queue}' not found. Available: {available}")
        
        attrs = {
            'Job_Name': job_name,
            'Account_Name': account,
            'Resource_List': {
                'select': select_spec,
                'walltime': walltime,
                'place': system_config.queues[queue].default_place,
                'filesystems': filesystems
            }
        }
        
        if additional_attrs:
            attrs.update(additional_attrs)
        
        with get_pbs_client(system_config) as pbs:
            job_id = pbs.submit(
                script_path=script_path,
                queue=queue,
                attrs=attrs
            )
        
        return {
            'job_id': job_id,
            'queue': queue,
            'system': system_config.name,
            'status': 'submitted'
        }
    
    @mcp.tool()
    def get_job_status(job_id: str) -> Dict[str, Any]:
        """
        Get detailed status for a specific job.
        
        Args:
            job_id: PBS job ID
            
        Returns:
            Dictionary with job status and attributes
        """
        validate_job_id(job_id)
        
        with get_pbs_client(system_config) as pbs:
            job = pbs.get_job(job_id)
        
        return format_job_status(job)
    
    @mcp.tool()
    def list_my_jobs(state_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        List all jobs for the current user.
        
        Args:
            state_filter: Optional state to filter by (Q, R, H, etc.)
            
        Returns:
            List of job summaries
        """
        with get_pbs_client(system_config) as pbs:
            if state_filter:
                jobs = pbs.select_jobs({'job_state': state_filter})
            else:
                jobs = pbs.stat_jobs()
        
        return [format_job_status(job) for job in jobs]
    
    @mcp.tool()
    def get_system_queues() -> Dict[str, Any]:
        """
        Get available queues for the current system.
        
        Returns:
            Dictionary of queue configurations
        """
        return {
            'system': system_config.name,
            'queues': {
                name: {
                    'max_walltime': q.max_walltime,
                    'max_nodes': q.max_nodes,
                    'filesystems': q.filesystems,
                    'description': q.description
                }
                for name, q in system_config.queues.items()
            }
        }
    
    # Additional tools: delete_job, hold_job, release_job, get_queue_info
    # (abbreviated for brevity - same pattern with system_config parameter)
```

#### `pbs_resources.py`
```python
from fastmcp import FastMCP
from borealis_mcp.config.system import SystemConfig, SystemConfigLoader
from borealis_mcp.core.pbs_client import get_pbs_client

def register_pbs_resources(mcp: FastMCP, system_config: SystemConfig, 
                          config_loader: SystemConfigLoader):
    """
    Register core PBS resources.
    
    Args:
        mcp: FastMCP server instance
        system_config: Current system configuration
        config_loader: System configuration loader for accessing all systems
    """
    
    @mcp.resource("pbs://system/info")
    def get_system_info() -> str:
        """Current system configuration and capabilities"""
        return f"""
# {system_config.display_name} ({system_config.facility})

## Hardware Specifications
- Total Nodes: {system_config.total_nodes}
- CPU: {system_config.cpu_model}
- Cores per Node: {system_config.cores_per_node}
- GPU: {system_config.gpu_type}
- GPUs per Node: {system_config.gpus_per_node}
- Memory: {system_config.memory_per_node} GB {system_config.memory_type}
- Interconnect: {system_config.interconnect}

## Available Queues
{_format_queues(system_config)}

## Filesystems
{_format_filesystems(system_config)}

## Recommended Modules
{', '.join(system_config.recommended_modules)}

## PBS Server
{system_config.pbs_server}
"""
    
    @mcp.resource("pbs://systems/all")
    def list_all_systems() -> str:
        """List all available system configurations"""
        systems = config_loader.discover_all_systems()
        
        lines = ["# Available HPC Systems\n"]
        for name, config in systems.items():
            current = " (CURRENT)" if name == system_config.name else ""
            lines.append(f"## {config.display_name}{current}")
            lines.append(f"- Name: {name}")
            lines.append(f"- Facility: {config.facility}")
            lines.append(f"- Nodes: {config.total_nodes}")
            lines.append(f"- GPUs/Node: {config.gpus_per_node}")
            lines.append(f"- GPU Type: {config.gpu_type}")
            lines.append("")
        
        return '\n'.join(lines)
    
    @mcp.resource("pbs://job/{job_id}")
    def get_job_details(job_id: str) -> str:
        """Detailed job information including resource usage"""
        with get_pbs_client(system_config) as pbs:
            job = pbs.get_job(job_id)
        
        return _format_job_details(job)
    
    @mcp.resource("pbs://queue/{queue_name}")
    def get_queue_status(queue_name: str) -> str:
        """Real-time queue status and job distribution"""
        with get_pbs_client(system_config) as pbs:
            queue = pbs.stat_queues(queue=queue_name)[0]
        
        return _format_queue_status(queue)

def _format_queues(system_config: SystemConfig) -> str:
    """Helper to format queue information"""
    lines = []
    for name, config in system_config.queues.items():
        lines.append(f"- **{name}**: {config.description}")
        lines.append(f"  - Max Walltime: {config.max_walltime}")
        lines.append(f"  - Max Nodes: {config.max_nodes}")
        lines.append(f"  - Filesystems: {', '.join(config.filesystems)}")
    return '\n'.join(lines)

def _format_filesystems(system_config: SystemConfig) -> str:
    """Helper to format filesystem information"""
    lines = []
    for name, path in system_config.filesystems.items():
        default = " (default)" if name in system_config.default_filesystems else ""
        lines.append(f"- {name}{default}: {path}")
    return '\n'.join(lines)

def _format_job_details(job) -> str:
    """Format detailed job information"""
    # Implementation
    pass

def _format_queue_status(queue) -> str:
    """Format queue status"""
    # Implementation
    pass
```

#### `pbs_prompts.py`
```python
from fastmcp import FastMCP

def register_pbs_prompts(mcp: FastMCP):
    """Register PBS workflow prompts"""
    
    @mcp.prompt()
    def job_submission_workflow(
        application_type: str = "generic",
        queue: str = "debug"
    ) -> str:
        """
        Guide for submitting jobs to Aurora.
        
        Args:
            application_type: Type of application (pytorch, tensorflow, generic)
            queue: Target queue name
        """
        return f"""
I need to help submit a {application_type} job to Aurora's {queue} queue.

Please follow this workflow:
1. Gather job requirements:
   - Number of nodes needed
   - Expected runtime (walltime)
   - Required filesystems
   - Account/project name

2. Use the appropriate application tool to generate the submit script:
   - For PyTorch: build_pytorch_submit_script()
   - For TensorFlow: build_tensorflow_submit_script()
   - For generic: build_generic_submit_script()

3. Review the generated script with the user

4. Submit using submit_pbs_job() with the generated script

5. Monitor with get_job_status() until complete

Let's start by asking the user for the job requirements.
"""
    
    @mcp.prompt()
    def job_debugging_workflow(job_id: str) -> str:
        """
        Guide for debugging failed or stuck jobs.
        
        Args:
            job_id: The PBS job ID to debug
        """
        return f"""
I need to help debug job {job_id}.

Investigation steps:
1. Get current job status with get_job_status()
2. Check the job resource (pbs://job/{job_id}) for details
3. Review queue status (pbs://queue/<queue_name>)
4. Check for common issues:
   - Walltime limits exceeded
   - Resource requests too high
   - Filesystem access problems
   - Module loading errors

Based on findings, suggest:
- Script modifications
- Resource adjustments
- Alternative queue if needed
"""
```

### 4. Application Layer (`applications/`)

Modular, extensible application-specific tools.

#### `base.py` - Application Interface
```python
from abc import ABC, abstractmethod
from typing import Dict, Any, List
from fastmcp import FastMCP
from borealis_mcp.config.system import SystemConfig

class ApplicationBase(ABC):
    """Base class for all application integrations"""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Application name (e.g., 'pytorch', 'tensorflow')"""
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description"""
        pass
    
    @property
    def tool_prefix(self) -> str:
        """Prefix for tool names to avoid conflicts"""
        return f"{self.name}_"
    
    @abstractmethod
    def register_tools(
        self, 
        mcp: FastMCP, 
        system_config: SystemConfig,
        app_config: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Register application-specific tools.
        
        Args:
            mcp: FastMCP server instance
            system_config: Current system configuration for adaptation
            app_config: Optional application-specific config (loaded automatically)
        """
        pass
    
    def get_metadata(self) -> Dict[str, Any]:
        """Return application metadata"""
        return {
            "name": self.name,
            "description": self.description,
            "version": getattr(self, 'version', '1.0.0')
        }
    
    def supports_system(self, system_config: SystemConfig) -> bool:
        """
        Check if this application supports the given system.
        Override to add system-specific requirements.
        
        Args:
            system_config: System configuration to check
            
        Returns:
            True if application supports this system
        """
        return True  # Default: support all systems
    
    def get_system_specific_settings(self, system_config: SystemConfig) -> Dict[str, Any]:
        """
        Get application settings specific to the current system.
        Override to provide system-specific configurations.
        
        Args:
            system_config: Current system configuration
            
        Returns:
            Dictionary of system-specific settings
        """
        return {}
```

#### `registry.py` - Application Registry
```python
from typing import Dict, List, Type
import importlib
import pkgutil
import sys
from pathlib import Path

from borealis_mcp.applications.base import ApplicationBase
from borealis_mcp.config.system import SystemConfig

class ApplicationRegistry:
    """Manages discovery and registration of applications"""
    
    def __init__(self):
        self.applications: Dict[str, ApplicationBase] = {}
    
    def discover_applications(self):
        """Auto-discover all application modules"""
        apps_dir = Path(__file__).parent
        
        for _, module_name, is_pkg in pkgutil.iter_modules([str(apps_dir)]):
            if is_pkg and module_name not in ['base', 'registry']:
                self._load_application(module_name)
    
    def _load_application(self, module_name: str):
        """Load a single application module"""
        try:
            module = importlib.import_module(
                f'borealis_mcp.applications.{module_name}'
            )
            
            # Look for Application class
            if hasattr(module, 'Application'):
                app_class = getattr(module, 'Application')
                app_instance = app_class()
                self.register(app_instance)
        except Exception as e:
            print(f"Warning: Failed to load application {module_name}: {e}",
                  file=sys.stderr)
    
    def register(self, application: ApplicationBase):
        """Register an application instance"""
        self.applications[application.name] = application
    
    def register_all(self, mcp, system_config: SystemConfig, config_loader):
        """
        Register all discovered applications with MCP server.
        
        Args:
            mcp: FastMCP server instance
            system_config: Current system configuration
            config_loader: SystemConfigLoader for loading app configs
        """
        for app in self.applications.values():
            # Check if app supports this system
            if app.supports_system(system_config):
                # Load app-specific config for this system
                app_config = config_loader.load_application_config(
                    app.name, 
                    system_config.name
                )
                
                # Register with config
                app.register_tools(mcp, system_config, app_config)
                print(f"Registered application: {app.name}", file=sys.stderr)
                if app_config:
                    print(f"  - Loaded config for {system_config.name}", file=sys.stderr)
            else:
                print(f"Skipping {app.name} (not supported on {system_config.name})", 
                      file=sys.stderr)
    
    def list_applications(self) -> List[Dict[str, Any]]:
        """Get metadata for all registered applications"""
        return [app.get_metadata() for app in self.applications.values()]
```

#### `hello_world/__init__.py` - Hello World Application
```python
from fastmcp import FastMCP
from borealis_mcp.applications.base import ApplicationBase
from borealis_mcp.applications.hello_world.templates import HelloWorldTemplates
from borealis_mcp.config.system import SystemConfig
from typing import Dict, Any, Optional

class Application(ApplicationBase):
    """Simple MPI hello world application for testing and demonstration"""
    
    @property
    def name(self) -> str:
        return "hello_world"
    
    @property
    def description(self) -> str:
        return "MPI Hello World - prints rank and hostname from each MPI process"
    
    def supports_system(self, system_config: SystemConfig) -> bool:
        """Hello world works on any system"""
        return True
    
    def register_tools(
        self, 
        mcp: FastMCP, 
        system_config: SystemConfig,
        app_config: Optional[Dict[str, Any]] = None
    ):
        """Register hello_world-specific tools"""
        
        # Get settings from app config or use defaults
        if app_config:
            modules = app_config.get('modules', system_config.recommended_modules)
            mpi_command = app_config.get('mpi', {}).get('command', 'mpiexec')
            mpi_flags = app_config.get('mpi', {}).get('flags', [])
            env_vars = app_config.get('environment', {})
            default_walltime = app_config.get('defaults', {}).get('walltime', '00:30:00')
            default_queue = app_config.get('defaults', {}).get('queue', 'debug')
        else:
            # Use system defaults
            modules = system_config.recommended_modules
            mpi_command = 'mpiexec'
            mpi_flags = []
            env_vars = {}
            default_walltime = '00:30:00'
            default_queue = 'debug'
        
        @mcp.tool()
        def build_hello_world_submit_script(
            script_path: str,
            num_nodes: int,
            ranks_per_node: int,
            walltime: str = default_walltime,
            queue: str = default_queue,
            job_name: str = "hello_world"
        ) -> str:
            """
            Generate PBS submit script for MPI Hello World.
            
            Prints rank number and hostname from each MPI process.
            Automatically adapts to the current system configuration.
            
            Args:
                script_path: Where to save the submit script
                num_nodes: Number of nodes to use
                ranks_per_node: MPI ranks per node
                walltime: Wall time in HH:MM:SS format
                queue: Queue name
                job_name: Name for the PBS job
                
            Returns:
                Path to generated submit script
            """
            template = HelloWorldTemplates.generate_submit_script(
                system_config=system_config,
                num_nodes=num_nodes,
                ranks_per_node=ranks_per_node,
                walltime=walltime,
                queue=queue,
                job_name=job_name,
                modules=modules,
                mpi_command=mpi_command,
                mpi_flags=mpi_flags,
                env_vars=env_vars
            )
            
            with open(script_path, 'w') as f:
                f.write(template)
            
            return script_path
        
        @mcp.tool()
        def get_hello_world_info() -> Dict[str, Any]:
            """
            Get information about hello_world configuration for current system.
            
            Returns:
                Dictionary with system-specific settings and recommendations
            """
            return {
                "system": system_config.display_name,
                "description": "MPI Hello World demonstration",
                "modules": modules,
                "mpi_command": mpi_command,
                "mpi_flags": mpi_flags,
                "environment": env_vars,
                "defaults": {
                    "walltime": default_walltime,
                    "queue": default_queue
                },
                "recommended_usage": {
                    "min_nodes": 1,
                    "max_nodes": system_config.queues.get(default_queue).max_nodes if default_queue in system_config.queues else "unknown",
                    "typical_ranks_per_node": system_config.cores_per_node
                },
                "example": f"build_hello_world_submit_script(script_path='submit.sh', num_nodes=2, ranks_per_node=4)"
            }
```

#### `hello_world/templates.py`
```python
from borealis_mcp.config.system import SystemConfig
from typing import Dict, Any, List

class HelloWorldTemplates:
    """PBS submit script templates for Hello World"""
    
    @staticmethod
    def generate_submit_script(
        system_config: SystemConfig,
        num_nodes: int,
        ranks_per_node: int,
        walltime: str,
        queue: str,
        job_name: str,
        modules: List[str],
        mpi_command: str,
        mpi_flags: List[str],
        env_vars: Dict[str, Any]
    ) -> str:
        """
        Generate MPI Hello World submit script.
        
        The script prints rank number and hostname from each MPI process.
        """
        
        # Build module load commands
        module_cmds = '\n'.join([f"module load {mod}" for mod in modules])
        
        # Build environment variable exports
        env_cmds = '\n'.join([f"export {key}={value}" for key, value in env_vars.items()])
        env_section = env_cmds if env_cmds else "# No additional environment variables"
        
        # Build MPI flags string
        flags_str = ' '.join(mpi_flags) if mpi_flags else ''
        
        # Default filesystems
        default_fs = ':'.join(system_config.default_filesystems)
        
        # Calculate total ranks
        total_ranks = num_nodes * ranks_per_node
        
        return f"""#!/bin/bash -l
#PBS -l select={num_nodes}:ncpus={system_config.cores_per_node}
#PBS -l walltime={walltime}
#PBS -l filesystems={default_fs}
#PBS -q {queue}
#PBS -A <PROJECT>
#PBS -N {job_name}

# System: {system_config.display_name}
# Total Ranks: {total_ranks} ({num_nodes} nodes × {ranks_per_node} ranks/node)

cd $PBS_O_WORKDIR

# Load modules
{module_cmds}

# Set environment
{env_section}

# Calculate MPI parameters
NNODES={num_nodes}
NRANKS_PER_NODE={ranks_per_node}
NTOTRANKS={total_ranks}

echo "Running Hello World on $NNODES nodes with $NRANKS_PER_NODE ranks per node"
echo "Total ranks: $NTOTRANKS"
echo "System: {system_config.display_name}"
echo ""

# Run Hello World - each rank prints its rank number and hostname
{mpi_command} -n $NTOTRANKS -ppn $NRANKS_PER_NODE {flags_str} bash -c '\\
    echo "Hello from rank ${{PMI_RANK:-$PMIX_RANK}} on $(hostname)"'

echo ""
echo "Hello World completed successfully"
"""
```

#### `generic/__init__.py` - Generic Application
```python
from fastmcp import FastMCP
from borealis_mcp.applications.base import ApplicationBase
from borealis_mcp.applications.generic.templates import GenericTemplates
from borealis_mcp.config.system import SystemConfig
from typing import Optional, Dict, Any

class Application(ApplicationBase):
    """Generic job support for arbitrary executables"""
    
    @property
    def name(self) -> str:
        return "generic"
    
    @property
    def description(self) -> str:
        return "Generic PBS job submission for any executable"
    
    def register_tools(
        self, 
        mcp: FastMCP, 
        system_config: SystemConfig,
        app_config: Optional[Dict[str, Any]] = None
    ):
        """Register generic tools"""
        
        @mcp.tool()
        def build_generic_submit_script(
            script_path: str,
            executable: str,
            arguments: str = "",
            num_nodes: int = 1,
            mpi_ranks_per_node: int = 1,
            environment_setup: str = ""
        ) -> str:
            """
            Generate basic PBS submit script for any executable.
            
            Args:
                script_path: Where to save submit script
                executable: Path to executable or command
                arguments: Command-line arguments
                num_nodes: Number of nodes
                mpi_ranks_per_node: MPI ranks per node
                environment_setup: Custom environment commands
                
            Returns:
                Path to generated submit script
            """
            template = GenericTemplates.get_basic_template(
                system_config=system_config,
                executable=executable,
                arguments=arguments,
                num_nodes=num_nodes,
                mpi_ranks_per_node=mpi_ranks_per_node,
                environment_setup=environment_setup
            )
            
            with open(script_path, 'w') as f:
                f.write(template)
            
            return script_path
```

### 5. Utilities (`utils/`)

Common utility functions.

#### `validation.py`
```python
import re
from borealis_mcp.config.constants import WALLTIME_PATTERN, FILESYSTEMS_PATTERN
from borealis_mcp.utils.errors import ValidationError

def validate_job_id(job_id: str) -> None:
    """Validate PBS job ID format"""
    pattern = r'^\d+\..+$'
    if not re.match(pattern, job_id):
        raise ValidationError(f"Invalid job ID format: {job_id}")

def validate_walltime(walltime: str) -> None:
    """Validate walltime format (HH:MM:SS)"""
    if not re.match(WALLTIME_PATTERN, walltime):
        raise ValidationError(
            f"Invalid walltime format: {walltime}. Expected HH:MM:SS"
        )

def validate_filesystems(filesystems: str) -> None:
    """Validate filesystem specification"""
    if not re.match(FILESYSTEMS_PATTERN, filesystems):
        raise ValidationError(
            f"Invalid filesystems format: {filesystems}. "
            f"Expected format like 'flare:home'"
        )

def validate_node_count(nodes: int, max_nodes: int) -> None:
    """Validate node count against queue limits"""
    if nodes < 1:
        raise ValidationError("Node count must be at least 1")
    if nodes > max_nodes:
        raise ValidationError(
            f"Requested {nodes} nodes exceeds queue limit of {max_nodes}"
        )
```

#### `formatting.py`
```python
from typing import Dict, Any, List

def format_job_status(job: Dict[str, Any]) -> Dict[str, Any]:
    """Format job status for MCP response"""
    return {
        'job_id': job.get('Job_Id'),
        'name': job.get('Job_Name'),
        'state': job.get('job_state'),
        'queue': job.get('queue'),
        'account': job.get('Account_Name'),
        'walltime': {
            'requested': job.get('Resource_List', {}).get('walltime'),
            'used': job.get('resources_used', {}).get('walltime')
        },
        'nodes': {
            'requested': job.get('Resource_List', {}).get('select'),
            'assigned': job.get('exec_host')
        }
    }

def format_queue_summary(queues: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Format queue summary for MCP response"""
    result = {}
    for queue in queues:
        result[queue['name']] = {
            'enabled': queue.get('enabled'),
            'started': queue.get('started'),
            'total_jobs': queue.get('total_jobs', 0),
            'state_count': queue.get('state_count', {}),
            'max_walltime': queue.get('resources_max', {}).get('walltime'),
            'max_nodes': queue.get('resources_max', {}).get('nodect')
        }
    return result
```

#### `errors.py`
```python
class BorealisError(Exception):
    """Base exception for Borealis MCP"""
    pass

class ValidationError(BorealisError):
    """Validation error"""
    pass

class PBSOperationError(BorealisError):
    """PBS operation failed"""
    pass

class ApplicationError(BorealisError):
    """Application-specific error"""
    pass
```

## Agent Workflow Examples

### Example 1: Submit Hello World MPI Job

```
User: "Please run the hello world example with 128 nodes on Aurora, with 6 ranks per node"

Agent workflow:
1. get_hello_world_info() → Learn about hello_world configuration on Aurora
   Returns:
   {
     "system": "Aurora",
     "mpi_command": "mpiexec",
     "mpi_flags": ["--cpu-bind", "depth"],
     "modules": ["frameworks", "mpich/icc-all-pmix-gpu/20240625"],
     "defaults": {"walltime": "00:30:00", "queue": "debug"}
   }

2. build_hello_world_submit_script(
     script_path="/home/user/submit_hello.sh",
     num_nodes=128,
     ranks_per_node=6,
     walltime="00:30:00",
     queue="debug",
     job_name="hello_world_128nodes"
   ) → Generate Aurora-optimized submit script
   Returns: "/home/user/submit_hello.sh"

3. submit_pbs_job(
     script_path="/home/user/submit_hello.sh",
     queue="debug",
     job_name="hello_world_128nodes",
     account="datascience",
     select_spec="128",
     walltime="00:30:00",
     filesystems="flare:home"
   ) → Submit to PBS
   Returns: {"job_id": "12345.aurora-pbs-01", "status": "submitted"}

4. get_job_status("12345.aurora-pbs-01") → Monitor progress
   Returns: {"state": "Q", "queue": "debug", ...}
```

### Example 2: Multi-System Awareness

```
User: "What's the difference in running hello_world on Aurora vs Polaris?"

Agent workflow:
1. Read resource pbs://systems/all to compare systems
2. Explain key differences:
   - Aurora: 12 GPUs/node, Intel MPI, frameworks module
   - Polaris: 4 GPUs/node, Cray MPI, different modules
   - Different MPI flags (--cpu-bind depth vs core)
3. Show that the same tool call adapts to each system
```

### Example 3: System-Adaptive Job Submission

```
User: "Run hello_world with 4 nodes and 8 ranks per node on both Aurora and Polaris"

Agent workflow (on Aurora):
1. build_hello_world_submit_script(
     script_path="submit_aurora.sh",
     num_nodes=4,
     ranks_per_node=8
   )
   → Generates script with:
   - modules: frameworks, mpich/icc-all-pmix-gpu/20240625
   - mpiexec with --cpu-bind depth
   - Intel-specific environment variables

Agent workflow (on Polaris):
1. build_hello_world_submit_script(
     script_path="submit_polaris.sh", 
     num_nodes=4,
     ranks_per_node=8
   )
   → Generates script with:
   - modules: conda, cray-mpich
   - mpiexec with --cpu-bind core
   - Cray-specific environment variables

Same tool call, different system-optimized outputs!
```

## System Configuration Benefits

### For Users

1. **Single Learning Curve**: Learn Borealis MCP once, use on all ALCF systems
2. **Portable Workflows**: Same agent prompts work across systems
3. **Optimal Performance**: Automatic system-specific optimizations
4. **Future-Proof**: New systems can be added without code changes

### For Application Developers

1. **System Awareness**: Applications receive full system configuration
2. **Adaptive Behavior**: Customize templates/settings per system
3. **Validation**: Check system compatibility before registration
4. **Testing**: Easy to test against multiple system configs

### For Administrators

1. **Easy Deployment**: Drop in new YAML configs for new systems
2. **Centralized Config**: User configs override built-in configs
3. **No Code Changes**: Update system specs without touching Python
4. **Multi-Tenancy**: Different users can define their own systems

### Configuration Hierarchy

```
1. Built-in configs (src/borealis_mcp/config/systems/*.yaml)
   ↓
2. User configs (config/systems/*.yaml) - OVERRIDE built-in
   ↓
3. Environment variables (BOREALIS_SYSTEM) - SELECT which to use
```

Example use case: User wants to test against a modified Aurora config with different queue limits:

```bash
# Copy built-in config
cp src/borealis_mcp/config/systems/aurora.yaml config/systems/aurora_test.yaml

# Edit queue limits
vim config/systems/aurora_test.yaml

# Use modified config
export BOREALIS_SYSTEM=aurora_test
python -m borealis_mcp.server
```

### Example 2: Multi-Stage Pipeline

```
User: "Run preprocessing on 2 nodes, then training on 8 nodes"

Agent workflow:
1. build_generic_submit_script(...) → Preprocessing script
2. submit_pbs_job(...) → Submit preprocessing
3. Monitor with get_job_status() until complete
4. build_pytorch_submit_script(...) → Training script with dependency
5. submit_pbs_job(...) → Submit training with -W depend=afterok:JOBID
6. Monitor both jobs
```

## Extension Guide

### Adding a New Application

Applications automatically receive the current system configuration, allowing them to adapt their behavior.

1. Create application directory:
```bash
mkdir -p src/borealis_mcp/applications/myapp
```

2. Implement `__init__.py`:
```python
from fastmcp import FastMCP
from borealis_mcp.applications.base import ApplicationBase
from borealis_mcp.config.system import SystemConfig

class Application(ApplicationBase):
    @property
    def name(self) -> str:
        return "myapp"
    
    @property
    def description(self) -> str:
        return "My application support"
    
    def supports_system(self, system_config: SystemConfig) -> bool:
        """Optional: Check if app supports this system"""
        # Example: Only support systems with GPUs
        return system_config.gpus_per_node > 0
    
    def get_system_specific_settings(self, system_config: SystemConfig) -> dict:
        """Optional: Get system-specific settings"""
        settings = {}
        
        if 'intel' in system_config.gpu_type.lower():
            settings['compiler'] = 'icx'
            settings['flags'] = ['-xCORE-AVX512']
        elif 'nvidia' in system_config.gpu_type.lower():
            settings['compiler'] = 'nvcc'
            settings['flags'] = ['-arch=sm_80']
        
        return settings
    
    def register_tools(self, mcp: FastMCP, system_config: SystemConfig):
        """Register tools with system awareness"""
        
        sys_settings = self.get_system_specific_settings(system_config)
        
        @mcp.tool()
        def build_myapp_submit_script(
            script_path: str,
            input_file: str
        ) -> str:
            """Generate submit script for myapp"""
            # Use system_config to adapt the script
            template = f"""#!/bin/bash -l
#PBS -l select=1:ncpus={system_config.cores_per_node}
#PBS -l filesystems={':'.join(system_config.default_filesystems)}
#PBS -q {system_config.get_default_queue().name}

# System: {system_config.display_name}
# Compiler: {sys_settings.get('compiler', 'default')}

myapp --input {input_file} {' '.join(sys_settings.get('flags', []))}
"""
            
            with open(script_path, 'w') as f:
                f.write(template)
            
            return script_path
```

3. Add templates in `templates.py` (optional)

4. Application is auto-discovered on server startup!

### Adding a New System Configuration

1. Create YAML config in `config/systems/`:
```bash
cat > config/systems/my_system.yaml << EOF
name: my_system
display_name: "My HPC System"
facility: "My Lab"
pbs_server: pbs.mylab.edu

hardware:
  total_nodes: 100
  cores_per_node: 48
  gpus_per_node: 4
  gpu_type: "NVIDIA H100"
  memory_per_node: 256
  memory_type: "DDR5"
  cpu_model: "AMD EPYC 9654"
  interconnect: "InfiniBand NDR"

queues:
  debug:
    max_walltime: "00:30:00"
    max_nodes: 4
    node_types: ["compute"]
    filesystems: ["scratch", "home"]
    description: "Quick testing"
    default_place: "scatter"

filesystems:
  scratch: "/scratch"
  home: "/home"

default_filesystems: ["scratch", "home"]

recommended_modules:
  - "gcc/12.2"
  - "openmpi/4.1"

custom_settings:
  # Any app-specific settings
  use_rdma: true
  network_fabric: "ib0"
EOF
```

2. Use the new system:
```bash
export BOREALIS_SYSTEM=my_system
python -m borealis_mcp.server
```

All existing applications automatically adapt to the new system!

### Adding New PBS Tools

Simply add new decorated functions to `core/pbs_tools.py`. They'll be automatically registered.

## Testing Strategy

### Unit Tests
- Test each application's script generation
- Test PBS tool validation
- Test formatting utilities

### Integration Tests
- Test against actual PBS server (mocked in CI)
- Test full submission workflow
- Test error handling

### Example Test Structure
```python
# tests/unit/test_pytorch_app.py
def test_pytorch_script_generation():
    app = PyTorchApplication()
    script = app.build_submit_script(...)
    assert "frameworks" in script
    assert "conda activate" in script
```

## Deployment

### On Aurora Login Node

1. Clone repository:
```bash
git clone https://github.com/your-org/borealis-mcp.git
cd borealis-mcp
```

2. Setup environment:
```bash
module load frameworks
python -m venv venv
source venv/bin/activate
pip install -e .
```

3. Configure environment:
```bash
# System auto-detected from hostname, or set explicitly:
export BOREALIS_SYSTEM=aurora
export PBS_ACCOUNT=datascience

# Optional: Use custom config directory
export BOREALIS_CONFIG_DIR=/path/to/custom/config
```

4. Run server:
```bash
python -m borealis_mcp.server
```

The server will automatically detect it's running on Aurora and load the appropriate configuration. You can override this with the `BOREALIS_SYSTEM` environment variable.

### Using Custom System Configurations

1. Create a config directory structure:
```bash
mkdir -p config/systems
```

2. Add your system configuration (see `config/systems/README.md` for template):
```bash
cat > config/systems/my_cluster.yaml << EOF
name: my_cluster
display_name: "My Research Cluster"
pbs_server: pbs.mysite.edu
# ... (see full template in design)
EOF
```

3. Run with custom config:
```bash
export BOREALIS_CONFIG_DIR=./config
export BOREALIS_SYSTEM=my_cluster
python -m borealis_mcp.server
```

### Multi-System Deployment

You can deploy one Borealis MCP instance per system, or use a shared deployment with system selection via environment variable:

```bash
# On Aurora
export BOREALIS_SYSTEM=aurora
python -m borealis_mcp.server

# On Polaris  
export BOREALIS_SYSTEM=polaris
python -m borealis_mcp.server
```

### Claude Desktop Configuration

```json
{
  "mcpServers": {
    "borealis": {
      "command": "ssh",
      "args": [
        "aurora.alcf.anl.gov",
        "source /path/to/borealis-mcp/venv/bin/activate && python -m borealis_mcp.server"
      ]
    }
  }
}
```

## Future Enhancements

### Phase 2: Compilation Support
- Tools for building codes on each system
- System-specific compiler flag recommendations
- Module dependency resolution
- Build script generation with system-aware compiler selection

### Phase 3: Advanced Monitoring
- Real-time job output streaming
- Resource usage visualization  
- Performance metrics collection
- Cross-system performance comparison

### Phase 4: Enhanced Multi-System Features
- Cross-system job orchestration (submit to multiple systems)
- Intelligent system selection based on requirements
- Workload balancing recommendations
- Cost/performance optimization across systems

### Phase 5: Workflow Orchestration
- DAG-based job dependencies
- Checkpoint/restart automation
- Data staging between systems
- Multi-system pipeline execution

## Security Considerations

1. **Privilege Checking**: Use PBS client privilege validation before operations
2. **Path Validation**: Sanitize all file paths before script generation
3. **Resource Limits**: Enforce queue-specific resource limits
4. **Account Validation**: Verify user has access to requested accounts
5. **Script Sanitization**: Validate generated scripts don't contain injection vulnerabilities

## Success Metrics

1. **Extensibility**: Can new applications be added in < 1 hour?
2. **System Portability**: Can a new system config be added in < 30 minutes?
3. **Agent Usability**: Can agents successfully submit jobs without human intervention?
4. **Error Recovery**: Do clear error messages lead to successful retry?
5. **Performance**: Script generation and PBS operations complete in < 5 seconds
6. **Adaptability**: Do applications automatically optimize for different systems?

## Conclusion

Borealis MCP provides a clean, extensible architecture for multi-system supercomputer integration. The user-configurable system definitions enable easy deployment across Aurora, Polaris, Sunspot, and future systems without code modifications. Applications automatically receive system configurations and can adapt their behavior accordingly, providing optimal performance while maintaining a consistent interface for AI agents. The separation of PBS core operations from application-specific logic, combined with the flexible configuration system, enables rapid addition of both new applications and new HPC systems.
