"""
Mock PBS client for local development and testing.

Use when pbs_ifl is not available (e.g., on laptops, CI environments).
Set BOREALIS_MOCK_PBS=1 to enable mock mode.
"""

import os
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence

from borealis_mcp.config.constants import ENV_BOREALIS_MOCK_PBS


class MockPBSException(RuntimeError):
    """Mock PBS exception for testing."""

    def __init__(self, message: str, errno: Optional[int] = None):
        super().__init__(message)
        self.errno = errno


@dataclass
class MockJobInfo:
    """Mock job info matching pbs_api.JobInfo interface."""

    name: str
    attrs: Dict[str, str] = field(default_factory=dict)


@dataclass
class MockQueueInfo:
    """Mock queue info matching pbs_api.QueueInfo interface."""

    name: str
    attrs: Dict[str, str] = field(default_factory=dict)


@dataclass
class MockServerInfo:
    """Mock server info matching pbs_api.ServerInfo interface."""

    name: str
    attrs: Dict[str, str] = field(default_factory=dict)


@dataclass
class MockNodeInfo:
    """Mock node info matching pbs_api.NodeInfo interface."""

    name: str
    attrs: Dict[str, str] = field(default_factory=dict)


class MockPBSClient:
    """
    Mock PBS client for development without pbs_ifl.

    Simulates PBS operations with in-memory job storage.
    """

    def __init__(self, server: Optional[str] = None):
        self.server = server or "mock-pbs-server"
        self._connected = False
        self._jobs: Dict[str, MockJobInfo] = {}
        self._job_counter = 1000

    def connect(self) -> "MockPBSClient":
        """Connect to mock PBS server."""
        self._connected = True
        return self

    def disconnect(self) -> None:
        """Disconnect from mock PBS server."""
        self._connected = False

    def __enter__(self) -> "MockPBSClient":
        return self.connect()

    def __exit__(self, *args: Any) -> None:
        self.disconnect()

    def stat_server(self) -> List[MockServerInfo]:
        """Return mock server info."""
        return [
            MockServerInfo(
                name=self.server,
                attrs={
                    "server_state": "Active",
                    "total_jobs": str(len(self._jobs)),
                    "pbs_version": "mock-1.0.0",
                },
            )
        ]

    def stat_jobs(
        self, job_id: Optional[str] = None, extend: Optional[str] = None
    ) -> List[MockJobInfo]:
        """Return mock job list."""
        if job_id:
            job = self._jobs.get(job_id)
            return [job] if job else []
        return list(self._jobs.values())

    def stat_queues(self, queue: Optional[str] = None) -> List[MockQueueInfo]:
        """Return mock queue info."""
        queues = [
            MockQueueInfo(
                name="debug",
                attrs={
                    "enabled": "True",
                    "started": "True",
                    "total_jobs": "0",
                    "resources_max.walltime": "01:00:00",
                    "resources_max.nodect": "8",
                },
            ),
            MockQueueInfo(
                name="workq",
                attrs={
                    "enabled": "True",
                    "started": "True",
                    "total_jobs": "0",
                    "resources_max.walltime": "24:00:00",
                    "resources_max.nodect": "496",
                },
            ),
            MockQueueInfo(
                name="prod",
                attrs={
                    "enabled": "True",
                    "started": "True",
                    "total_jobs": "0",
                    "resources_max.walltime": "72:00:00",
                    "resources_max.nodect": "4096",
                },
            ),
        ]
        if queue:
            return [q for q in queues if q.name == queue]
        return queues

    def stat_nodes(self, node: Optional[str] = None) -> List[MockNodeInfo]:
        """Return mock node info."""
        nodes = [
            MockNodeInfo(
                name=f"x1000c0s0b0n{i}",
                attrs={
                    "state": "free",
                    "resources_available.ncpus": "208",
                    "resources_available.ngpus": "12",
                },
            )
            for i in range(4)
        ]
        if node:
            return [n for n in nodes if n.name == node]
        return nodes

    def select_jobs(self, criteria: Mapping[str, Any]) -> List[MockJobInfo]:
        """Select jobs matching criteria."""
        results = []
        for job in self._jobs.values():
            match = True
            for key, value in criteria.items():
                if job.attrs.get(key) != str(value):
                    match = False
                    break
            if match:
                results.append(job)
        return results

    def submit(
        self,
        script_path: str,
        queue: Optional[str] = None,
        attrs: Optional[Mapping[str, Any]] = None,
    ) -> str:
        """Submit a mock job."""
        job_id = f"{self._job_counter}.{self.server}"
        self._job_counter += 1

        job_attrs: Dict[str, str] = {
            "Job_Name": attrs.get("Job_Name", "mock_job") if attrs else "mock_job",
            "job_state": "Q",
            "queue": queue or "workq",
            "ctime": datetime.now().isoformat(),
            "Job_Owner": "mockuser@localhost",
        }

        if attrs:
            if "Account_Name" in attrs:
                job_attrs["Account_Name"] = str(attrs["Account_Name"])
            if "Resource_List" in attrs:
                for key, value in attrs["Resource_List"].items():
                    job_attrs[f"Resource_List.{key}"] = str(value)

        self._jobs[job_id] = MockJobInfo(name=job_id, attrs=job_attrs)
        return job_id

    def get_job(self, job_id: str) -> MockJobInfo:
        """Get a specific job."""
        if job_id not in self._jobs:
            raise MockPBSException(f"Job {job_id} not found", errno=15001)
        return self._jobs[job_id]

    def delete_job(self, job_id: str, force: bool = False) -> None:
        """Delete a job."""
        if job_id in self._jobs:
            del self._jobs[job_id]

    def delete_jobs(self, job_ids: Sequence[str]) -> List[tuple]:
        """Delete multiple jobs."""
        results = []
        for job_id in job_ids:
            if job_id in self._jobs:
                del self._jobs[job_id]
                results.append((job_id, 0))
            else:
                results.append((job_id, 1))
        return results

    def hold_job(self, job_id: str, hold: int = 1) -> None:
        """Hold a job."""
        if job_id in self._jobs:
            self._jobs[job_id].attrs["job_state"] = "H"

    def release_job(self, job_id: str, hold: int = 1) -> None:
        """Release a held job."""
        if job_id in self._jobs:
            self._jobs[job_id].attrs["job_state"] = "Q"

    def alter_job(self, job_id: str, updates: Mapping[str, Any]) -> None:
        """Alter job attributes."""
        if job_id not in self._jobs:
            raise MockPBSException(f"Job {job_id} not found", errno=15001)
        for key, value in updates.items():
            self._jobs[job_id].attrs[key] = str(value)

    def list_queued(self) -> List[str]:
        """List queued job IDs."""
        return [
            job.name
            for job in self._jobs.values()
            if job.attrs.get("job_state") == "Q"
        ]

    def list_running(self) -> List[str]:
        """List running job IDs."""
        return [
            job.name
            for job in self._jobs.values()
            if job.attrs.get("job_state") == "R"
        ]

    def get_job_summary(self) -> Dict[str, int]:
        """Get job counts by state."""
        summary: Dict[str, int] = {}
        for job in self._jobs.values():
            state = job.attrs.get("job_state", "unknown")
            summary[state] = summary.get(state, 0) + 1
        return summary


def is_mock_mode() -> bool:
    """Check if mock mode is enabled."""
    return os.environ.get(ENV_BOREALIS_MOCK_PBS, "").lower() in ("1", "true", "yes")


@contextmanager
def get_mock_pbs_client(
    server: Optional[str] = None,
) -> Iterator[MockPBSClient]:
    """Context manager for mock PBS client."""
    client = MockPBSClient(server=server)
    try:
        client.connect()
        yield client
    finally:
        client.disconnect()
