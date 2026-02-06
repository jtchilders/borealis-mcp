"""Workspace management for Borealis MCP.

Provides job workspace creation and management on the HPC filesystem.
Workspaces are directories where job scripts, inputs, and outputs are stored.
"""

import json
import os
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from borealis_mcp.config.constants import ENV_BOREALIS_JOB_WORKSPACE
from borealis_mcp.utils.logging import get_logger

logger = get_logger("workspace")

# Metadata filename stored in each workspace
WORKSPACE_METADATA_FILE = ".borealis_workspace.json"


@dataclass
class WorkspaceInfo:
    """Information about a job workspace."""

    workspace_id: str
    path: str
    job_name: str
    created_at: str
    system: str
    status: str = "active"  # active, submitted, completed, failed
    job_id: Optional[str] = None
    script_path: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkspaceInfo":
        """Create from dictionary."""
        return cls(
            workspace_id=data["workspace_id"],
            path=data["path"],
            job_name=data["job_name"],
            created_at=data["created_at"],
            system=data["system"],
            status=data.get("status", "active"),
            job_id=data.get("job_id"),
            script_path=data.get("script_path"),
            metadata=data.get("metadata", {}),
        )


class WorkspaceManager:
    """
    Manages job workspaces on the HPC filesystem.

    Workspaces are directories that contain:
    - PBS submit scripts
    - Job input files
    - Job output files
    - Metadata about the job
    """

    def __init__(
        self,
        base_path: Optional[str] = None,
        system_name: str = "unknown",
    ):
        """
        Initialize the workspace manager.

        Args:
            base_path: Base directory for workspaces. If None, uses:
                       1. BOREALIS_JOB_WORKSPACE env var
                       2. $HOME/borealis_jobs
            system_name: Name of the current HPC system
        """
        self.system_name = system_name

        # Determine base path
        if base_path:
            self._base_path = Path(base_path)
        elif os.environ.get(ENV_BOREALIS_JOB_WORKSPACE):
            self._base_path = Path(os.environ[ENV_BOREALIS_JOB_WORKSPACE])
        else:
            self._base_path = Path.home() / "borealis_jobs"

    @property
    def base_path(self) -> Path:
        """Get the base path for workspaces."""
        return self._base_path

    def _generate_workspace_id(self) -> str:
        """Generate a unique workspace ID."""
        return uuid.uuid4().hex[:12]

    def _get_workspace_dirname(self, job_name: str, timestamp: datetime) -> str:
        """Generate workspace directory name."""
        ts_str = timestamp.strftime("%Y%m%d_%H%M%S")
        # Sanitize job name for filesystem
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in job_name)
        return f"{safe_name}_{ts_str}"

    def _load_workspace_metadata(self, workspace_path: Path) -> Optional[WorkspaceInfo]:
        """Load workspace metadata from file."""
        metadata_file = workspace_path / WORKSPACE_METADATA_FILE
        if not metadata_file.exists():
            return None
        try:
            with open(metadata_file) as f:
                data = json.load(f)
            return WorkspaceInfo.from_dict(data)
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to load workspace metadata from {metadata_file}: {e}")
            return None

    def _save_workspace_metadata(self, info: WorkspaceInfo) -> None:
        """Save workspace metadata to file."""
        metadata_file = Path(info.path) / WORKSPACE_METADATA_FILE
        with open(metadata_file, "w") as f:
            json.dump(info.to_dict(), f, indent=2)

    def create_workspace(
        self,
        job_name: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> WorkspaceInfo:
        """
        Create a new job workspace.

        Args:
            job_name: Name for the job (used in directory name)
            metadata: Optional additional metadata to store

        Returns:
            WorkspaceInfo with workspace details

        Raises:
            OSError: If workspace directory cannot be created
        """
        timestamp = datetime.now()
        workspace_id = self._generate_workspace_id()
        dirname = self._get_workspace_dirname(job_name, timestamp)
        workspace_path = self._base_path / dirname

        # Create the workspace directory
        workspace_path.mkdir(parents=True, exist_ok=False)
        logger.info(f"Created workspace: {workspace_path}")

        # Create workspace info
        info = WorkspaceInfo(
            workspace_id=workspace_id,
            path=str(workspace_path),
            job_name=job_name,
            created_at=timestamp.isoformat(),
            system=self.system_name,
            status="active",
            metadata=metadata or {},
        )

        # Save metadata
        self._save_workspace_metadata(info)

        return info

    def get_workspace(self, workspace_id: str) -> Optional[WorkspaceInfo]:
        """
        Get workspace information by ID.

        Args:
            workspace_id: Workspace identifier

        Returns:
            WorkspaceInfo if found, None otherwise
        """
        # Search through workspaces to find matching ID
        if not self._base_path.exists():
            return None

        for workspace_dir in self._base_path.iterdir():
            if not workspace_dir.is_dir():
                continue
            info = self._load_workspace_metadata(workspace_dir)
            if info and info.workspace_id == workspace_id:
                return info

        return None

    def get_workspace_by_path(self, path: str) -> Optional[WorkspaceInfo]:
        """
        Get workspace information by path.

        Args:
            path: Full path to workspace directory

        Returns:
            WorkspaceInfo if found, None otherwise
        """
        workspace_path = Path(path)
        if not workspace_path.exists():
            return None
        return self._load_workspace_metadata(workspace_path)

    def list_workspaces(
        self,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[WorkspaceInfo]:
        """
        List existing workspaces.

        Args:
            status: Filter by status (active, submitted, completed, failed)
            limit: Maximum number of workspaces to return

        Returns:
            List of WorkspaceInfo objects, sorted by creation time (newest first)
        """
        workspaces = []

        if not self._base_path.exists():
            return workspaces

        for workspace_dir in self._base_path.iterdir():
            if not workspace_dir.is_dir():
                continue
            info = self._load_workspace_metadata(workspace_dir)
            if info:
                if status is None or info.status == status:
                    workspaces.append(info)

        # Sort by creation time (newest first)
        workspaces.sort(key=lambda w: w.created_at, reverse=True)

        return workspaces[:limit]

    def update_workspace(
        self,
        workspace_id: str,
        status: Optional[str] = None,
        job_id: Optional[str] = None,
        script_path: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[WorkspaceInfo]:
        """
        Update workspace information.

        Args:
            workspace_id: Workspace identifier
            status: New status
            job_id: PBS job ID if submitted
            script_path: Path to submit script
            metadata: Additional metadata to merge

        Returns:
            Updated WorkspaceInfo if found, None otherwise
        """
        info = self.get_workspace(workspace_id)
        if not info:
            return None

        if status:
            info.status = status
        if job_id:
            info.job_id = job_id
        if script_path:
            info.script_path = script_path
        if metadata:
            info.metadata.update(metadata)

        self._save_workspace_metadata(info)
        return info

    def cleanup_workspace(self, workspace_id: str, force: bool = False) -> bool:
        """
        Remove a workspace directory.

        Args:
            workspace_id: Workspace identifier
            force: If True, remove even if job is still active

        Returns:
            True if workspace was removed, False otherwise
        """
        info = self.get_workspace(workspace_id)
        if not info:
            logger.warning(f"Workspace {workspace_id} not found")
            return False

        # Check if safe to remove
        if not force and info.status in ("active", "submitted"):
            logger.warning(
                f"Workspace {workspace_id} has status '{info.status}'. "
                "Use force=True to remove anyway."
            )
            return False

        workspace_path = Path(info.path)
        if workspace_path.exists():
            shutil.rmtree(workspace_path)
            logger.info(f"Removed workspace: {workspace_path}")
            return True

        return False

    def cleanup_old_workspaces(self, days: int = 30) -> int:
        """
        Remove workspaces older than specified days.

        Args:
            days: Remove workspaces older than this many days

        Returns:
            Number of workspaces removed
        """
        if days <= 0:
            return 0

        cutoff = datetime.now().timestamp() - (days * 24 * 60 * 60)
        removed = 0

        for info in self.list_workspaces(limit=1000):
            try:
                created = datetime.fromisoformat(info.created_at).timestamp()
                if created < cutoff and info.status in ("completed", "failed"):
                    if self.cleanup_workspace(info.workspace_id, force=True):
                        removed += 1
            except ValueError:
                continue

        logger.info(f"Cleaned up {removed} old workspaces")
        return removed

    def get_script_path(self, workspace_id: str, script_name: str = "submit.sh") -> str:
        """
        Get the path for a submit script in a workspace.

        Args:
            workspace_id: Workspace identifier
            script_name: Name of the script file

        Returns:
            Full path to the script file

        Raises:
            ValueError: If workspace not found
        """
        info = self.get_workspace(workspace_id)
        if not info:
            raise ValueError(f"Workspace {workspace_id} not found")
        return str(Path(info.path) / script_name)
