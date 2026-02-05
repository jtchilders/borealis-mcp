"""Pytest configuration and fixtures for Borealis MCP tests."""

import os
import pytest
from pathlib import Path


@pytest.fixture(autouse=True)
def enable_mock_pbs():
    """Enable mock PBS mode for all tests."""
    os.environ["BOREALIS_MOCK_PBS"] = "1"
    yield
    # Cleanup
    if "BOREALIS_MOCK_PBS" in os.environ:
        del os.environ["BOREALIS_MOCK_PBS"]


@pytest.fixture
def config_dir():
    """Return the path to the test config directory."""
    return Path(__file__).parent.parent / "config"


@pytest.fixture
def sample_account():
    """Provide a sample PBS account for tests."""
    return "test_project"


@pytest.fixture
def mock_env(sample_account):
    """Set up mock environment variables."""
    old_env = os.environ.copy()
    os.environ["PBS_ACCOUNT"] = sample_account
    os.environ["BOREALIS_MOCK_PBS"] = "1"
    yield
    os.environ.clear()
    os.environ.update(old_env)
