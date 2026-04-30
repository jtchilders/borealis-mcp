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

### On ALCF Login Nodes (Direct SSH Launch)

Claude Code can launch the MCP server directly over SSH. Because Claude Code cannot respond to interactive prompts, SSH must connect without requiring a password or MFA challenge. The recommended approach is **SSH ControlMaster**, which multiplexes subsequent connections over an already-authenticated session.

#### Step 1: Configure SSH ControlMaster

Add the following to your local `~/.ssh/config`:

```
Host aurora.alcf.anl.gov
    ControlMaster auto
    ControlPath ~/.ssh/control-%h-%p-%r
    ControlPersist 8h
```

`ControlPersist 8h` keeps the master connection alive for 8 hours after you close it, so Claude Code can reconnect without prompting.

#### Step 2: Open the master connection

Before starting Claude Code, open one SSH session manually (this is where you complete MFA):

```bash
ssh aurora.alcf.anl.gov
```

Leave this terminal open, or let `ControlPersist` hold it in the background after you exit.

#### Step 3: Configure Claude Code

Subsequent SSH connections will reuse the authenticated master. Add to your Claude Code MCP settings (`~/.claude/settings.json`):

```json
{
  "mcpServers": {
    "borealis": {
      "command": "ssh",
      "args": [
        "aurora.alcf.anl.gov",
        "cd /path/to/borealis-mcp && ./start_borealis.sh aurora"
      ]
    }
  }
}
```

For Polaris or Sunspot, replace the host and system name accordingly:

```json
{
  "mcpServers": {
    "borealis": {
      "command": "ssh",
      "args": [
        "polaris.alcf.anl.gov",
        "cd /path/to/borealis-mcp && ./start_borealis.sh polaris"
      ]
    }
  }
}
```

> **Note**: `start_borealis.sh` must be *executed* (not sourced) here so that it sets the PBS environment variables and then launches the server. Claude Code communicates with it via stdio.

### Remote Access via SSH Tunnel

This is the recommended workflow for using Borealis with Claude Code when connecting to an ALCF system from your local machine.

> **Security Note**: The HTTP transport has no authentication. It binds to `localhost` only, but other users on the same login node could potentially reach your server. Use on trusted networks. Token-based authentication is planned for a future release.

#### Step 1: One-time setup on Aurora

Log in and clone the repository:

```bash
ssh username@aurora.alcf.anl.gov

git clone --recursive https://github.com/argonne-lcf/borealis-mcp.git
cd borealis-mcp

# If you already cloned without --recursive:
git submodule update --init --recursive

python3 -m venv venv
source venv/bin/activate
pip install -e .
```

#### Step 2: Set your PBS account on Aurora

Add your project allocation to `~/.bashrc` (or `~/.bash_profile`) so it is available to the server:

```bash
echo 'export PBS_ACCOUNT=your_project_allocation' >> ~/.bashrc
source ~/.bashrc
```

#### Step 3: Start the server and tunnel

**Option A — Single command (recommended).** From your **local machine**, run the helper script. It establishes the SSH tunnel and starts the MCP server over a single connection with one MFA prompt:

```bash
./tools/start_borealis_tunnel.sh your_aurora_username
# Optional second argument overrides the remote repo path (default: ~/borealis-mcp)
./tools/start_borealis_tunnel.sh your_aurora_username ~/path/to/borealis-mcp
```

Keep this terminal open. Press `Ctrl+C` to stop the server and close the tunnel.

**Option B — Two terminals.** Use this if you want the server and tunnel managed separately (requires MFA twice).

*Terminal 1* — log in to Aurora and start the server:

```bash
ssh username@aurora.alcf.anl.gov
cd ~/borealis-mcp
source start_borealis.sh aurora          # sets PBS_SERVER, PBS_ACCOUNT, PYTHONPATH
python -m borealis_mcp.server --transport http --port 9000
```

*Terminal 2* — open the port-forwarding tunnel from your local machine:

```bash
ssh -N -L 9000:localhost:9000 username@aurora.alcf.anl.gov
```

#### Step 4: Configure Claude Code

Claude Code requires the stdio HTTP bridge to connect to the server. It cannot use `type: "sse"` directly because it attempts OAuth metadata discovery, which FastMCP does not implement.

Copy the bridge script to your local machine:

```bash
scp username@aurora.alcf.anl.gov:~/borealis-mcp/tools/http_bridge.py ~/http_bridge.py
pip install requests   # the bridge's only dependency
```

Then add the following to your Claude Code MCP settings. The settings file is `~/.claude/settings.json` (user-wide) or `.claude/settings.json` inside a specific project:

```json
{
  "mcpServers": {
    "borealis": {
      "command": "python3",
      "args": ["/home/YOUR_USERNAME/http_bridge.py", "http://localhost:9000/mcp"]
    }
  }
}
```

#### Step 5: Start Claude Code

With the tunnel open and the server running, start Claude Code normally. The `borealis` MCP server will be available and Claude can submit and manage PBS jobs on Aurora on your behalf.

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
