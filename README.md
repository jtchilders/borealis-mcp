# Borealis MCP

An MCP (Model Context Protocol) server for AI agent interaction with ALCF supercomputers (Aurora, Polaris, Sunspot).

Borealis enables AI agents like Claude to submit and manage PBS jobs, query system status, and generate optimized submit scripts for ALCF systems.

## Features

- **PBS Job Management**: Submit, monitor, hold, release, and delete jobs
- **System-Aware**: Auto-detects and adapts to Aurora, Polaris, or Sunspot
- **Application Plugins**: Extensible architecture for domain-specific tools
- **Mock Mode**: Develop and test locally without PBS access
- **Remote Access**: SSH tunnel support for external users

## Quick Start

### Installation

```bash
# Clone the repository with submodules
git clone --recursive https://github.com/argonne-lcf/borealis-mcp.git
cd borealis-mcp

# If you already cloned without --recursive, initialize submodules:
git submodule update --init --recursive

# Create virtual environment (Python 3.10+)
python3 -m venv venv
source venv/bin/activate

# Install in development mode
pip install -e .
```

### Running Locally (Mock Mode)

For development without PBS access:

```bash
# Enable mock mode and run
BOREALIS_MOCK_PBS=1 python -m borealis_mcp.server
```

Or use the `--mock` flag:

```bash
python -m borealis_mcp.server --mock
```

### Running on ALCF Systems

On Aurora, Polaris, or Sunspot login nodes, use the provided startup script:

```bash
# Run on Aurora (default)
source start_borealis.sh

# Or specify the system explicitly
source start_borealis.sh aurora
source start_borealis.sh polaris
source start_borealis.sh sunspot

# Override the default account if needed
PBS_ACCOUNT=my_project source start_borealis.sh aurora
```

The `start_borealis.sh` script automatically:
- Activates the virtual environment
- Sets `PBS_SERVER` for the target system
- Adds the bundled `pbs-python-api` to `PYTHONPATH`
- Launches the MCP server

## Claude Code Integration

### Local Development (Mock Mode)

Add to your Claude Code MCP settings (`~/.claude/claude_desktop_config.json` on Mac):

```json
{
  "mcpServers": {
    "borealis": {
      "command": "/path/to/borealis-mcp/venv/bin/python",
      "args": ["-m", "borealis_mcp.server", "--mock"],
      "cwd": "/path/to/borealis-mcp"
    }
  }
}
```

### On ALCF Login Nodes (Direct Access)

If you have direct SSH access to ALCF systems, use the startup script:

```json
{
  "mcpServers": {
    "borealis": {
      "command": "ssh",
      "args": [
        "aurora.alcf.anl.gov",
        "cd /path/to/borealis-mcp && source ./start_borealis.sh"
      ]
    }
  }
}
```

Or specify a different system:

```json
{
  "mcpServers": {
    "borealis": {
      "command": "ssh",
      "args": [
        "polaris.alcf.anl.gov",
        "cd /path/to/borealis-mcp && source ./start_borealis.sh polaris"
      ]
    }
  }
}
```

### Remote Access via SSH Tunnel

For external users (requires MFA):

> **Security Note**: The HTTP transport currently has no authentication. While it binds to localhost only, other users on the same login node could potentially access your server. Use with caution and consider this for trusted environments only. Token-based authentication is planned for a future release.

1. **Start the tunnel and server:**
   ```bash
   # In one terminal, establish SSH tunnel (will prompt for MFA)
   ssh -L 9000:localhost:9000 username@aurora.alcf.anl.gov

   # On Aurora, start the server in HTTP mode
   cd /path/to/borealis-mcp
   source venv/bin/activate
   export PBS_ACCOUNT=your_project
   python -m borealis_mcp.server --transport http --port 9000
   ```

2. **Configure Claude Code to use the HTTP bridge:**
   ```json
   {
     "mcpServers": {
       "borealis": {
         "command": "/path/to/borealis-mcp/venv/bin/python",
         "args": ["/path/to/borealis-mcp/tools/http_bridge.py", "http://localhost:9000/mcp"]
       }
     }
   }
   ```

Or use the helper script:
```bash
./tools/start_borealis_tunnel.sh username
```

## Available Tools

### Core PBS Tools
- `submit_pbs_job` - Submit a job from a script file
- `get_job_status` - Get status of a specific job
- `list_jobs` - List jobs with optional state/queue filters
- `delete_job` - Delete a job
- `hold_job` / `release_job` - Hold or release a job
- `get_queue_info` - Get queue information
- `get_system_info` - Get current system configuration

### Application Tools
- `build_hello_world_submit_script` - Generate MPI hello world script
- `get_hello_world_info` - Get hello world configuration
- `build_generic_submit_script` - Generate script for any executable
- `get_generic_info` - Get generic job configuration

## Available Resources

- `pbs://system/current` - Current system configuration
- `pbs://systems/all` - All available systems
- `pbs://queues` - Queue information
- `pbs://jobs/summary` - Job summary by state
- `pbs://filesystems` - Filesystem information

## Configuration

### Environment Variables

| Variable | Description |
|----------|-------------|
| `PBS_ACCOUNT` | **Required.** Your PBS project allocation |
| `BOREALIS_SYSTEM` | Override system detection (aurora, polaris, sunspot) |
| `BOREALIS_MOCK_PBS` | Set to `1` for mock mode (local development) |
| `BOREALIS_CONFIG_DIR` | Custom config directory path |

### System Configurations

System configs are in `config/systems/`. See `config/systems/README.md` for adding new systems.

## Development

### Running Tests

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests (automatically uses mock mode)
pytest
```

### Adding New Applications

1. Create a new directory under `src/borealis_mcp/applications/`
2. Implement `Application` class inheriting from `ApplicationBase`
3. The application is auto-discovered on server startup

See `applications/hello_world/` for an example.

## License

MIT
