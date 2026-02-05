"""Constants for Borealis MCP."""

import re

# Validation patterns
WALLTIME_PATTERN = r'^\d{1,3}:\d{2}:\d{2}$'
FILESYSTEMS_PATTERN = r'^[a-zA-Z0-9_]+(:[a-zA-Z0-9_]+)*$'
JOB_ID_PATTERN = r'^\d+\..+$'

# Pre-compiled regex for performance
WALLTIME_REGEX = re.compile(WALLTIME_PATTERN)
FILESYSTEMS_REGEX = re.compile(FILESYSTEMS_PATTERN)
JOB_ID_REGEX = re.compile(JOB_ID_PATTERN)

# Job states
JOB_STATES = {
    'Q': 'Queued',
    'R': 'Running',
    'H': 'Held',
    'E': 'Exiting',
    'F': 'Finished',
    'S': 'Suspended',
    'W': 'Waiting',
    'T': 'Transiting',
    'B': 'Array job running',
    'X': 'Subjob completed',
}

# Default values
DEFAULT_WALLTIME = '01:00:00'
DEFAULT_QUEUE = 'debug'

# Environment variable names
ENV_BOREALIS_SYSTEM = 'BOREALIS_SYSTEM'
ENV_BOREALIS_CONFIG_DIR = 'BOREALIS_CONFIG_DIR'
ENV_BOREALIS_MOCK_PBS = 'BOREALIS_MOCK_PBS'
ENV_PBS_ACCOUNT = 'PBS_ACCOUNT'
ENV_PBS_SERVER = 'PBS_SERVER'
ENV_PBS_DEFAULT = 'PBS_DEFAULT'
