# System Configurations

This directory contains YAML configuration files for each HPC system.

## Adding a New System

1. Create a new YAML file named `<system_name>.yaml`
2. Follow the structure below
3. The system will be auto-discovered on server startup

## Configuration Structure

```yaml
name: my_system                    # Unique identifier (matches filename)
display_name: "My HPC System"      # Human-readable name
facility: "My Research Lab"        # Organization/facility name
pbs_server: pbs.mylab.edu          # PBS server hostname

hardware:
  total_nodes: 100                 # Total compute nodes
  cores_per_node: 48               # CPU cores per node
  gpus_per_node: 4                 # GPUs per node (0 if none)
  gpu_type: "NVIDIA H100"          # GPU model name
  memory_per_node: 256             # RAM in GB
  memory_type: "DDR5"              # Memory type
  cpu_model: "AMD EPYC 9654"       # CPU model name
  interconnect: "InfiniBand NDR"   # Network interconnect

queues:
  debug:                           # Queue name
    max_walltime: "00:30:00"       # Maximum walltime (HH:MM:SS)
    max_nodes: 4                   # Maximum nodes per job
    node_types: ["compute"]        # Node types allowed
    filesystems: ["scratch", "home"]  # Available filesystems
    description: "Quick testing"   # Human-readable description
    default_place: "scatter"       # PBS place directive
    priority: 100                  # Higher = more likely default

  prod:
    max_walltime: "24:00:00"
    max_nodes: 80
    node_types: ["compute"]
    filesystems: ["scratch", "home"]
    description: "Production jobs"
    default_place: "scatter"
    priority: 50

filesystems:
  scratch: "/scratch"              # Filesystem name: path
  home: "/home"

default_filesystems:               # Filesystems for #PBS -l filesystems
  - "scratch"
  - "home"

recommended_modules:               # Modules to load by default
  - "gcc/12.2"
  - "openmpi/4.1"

custom_settings:                   # Application-specific settings
  mpi:
    command: "mpiexec"
    flags:
      - "--cpu-bind"
      - "core"
  environment:
    MY_VAR: "value"
```

## Notes

- Files starting with `local` are ignored (for local testing)
- The `debug` queue is used as default if present
- Custom settings are passed to applications for system-specific behavior
