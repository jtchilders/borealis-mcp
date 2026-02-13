"""Workspace file access tools for Borealis MCP.

Provides secure file access to job workspace directories, enabling remote
Claude instances to discover and retrieve files from completed jobs.

Security features:
- All operations validate workspace_id exists
- Path traversal attacks are blocked (../ and absolute paths rejected)
- Only files within workspace directories are accessible
- Size limits prevent memory exhaustion
- All access is logged
"""

import base64
import fnmatch
import hashlib
import os
import stat
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from fastmcp import FastMCP

from borealis_mcp.utils.logging import get_logger

if TYPE_CHECKING:
    from borealis_mcp.core.workspace import WorkspaceManager

logger = get_logger("workspace_files")

# Default size limits
DEFAULT_MAX_READ_SIZE_MB = 10.0
DEFAULT_MAX_LIST_FILES = 1000

# File type detection based on extension
FILE_TYPE_MAP = {
    ".hdf5": "hdf5",
    ".h5": "hdf5",
    ".log": "log",
    ".txt": "text",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".sh": "script",
    ".py": "python",
    ".lhe": "lhe",
    ".hepmc": "hepmc",
    ".root": "root",
    ".tex": "tex",
}

# Binary file extensions (will use base64 encoding)
BINARY_EXTENSIONS = {
    ".hdf5", ".h5", ".root", ".gz", ".tar", ".zip",
    ".png", ".jpg", ".jpeg", ".gif", ".pdf",
}


def _validate_workspace_path(
    workspace_manager: "WorkspaceManager",
    workspace_id: str,
) -> Optional[Path]:
    """Validate workspace exists and return its path.

    Returns None if workspace doesn't exist.
    """
    workspace_info = workspace_manager.get_workspace(workspace_id)
    if not workspace_info:
        return None
    return Path(workspace_info.path)


def _validate_filename(filename: str) -> bool:
    """Validate filename is safe (no path traversal).

    Returns True if filename is safe, False otherwise.
    """
    # Reject empty filenames
    if not filename:
        return False

    # Reject absolute paths
    if filename.startswith("/"):
        return False

    # Reject path traversal attempts
    if ".." in filename:
        return False

    # Reject paths starting with ~
    if filename.startswith("~"):
        return False

    return True


def _get_file_type(filepath: Path) -> str:
    """Determine file type from extension."""
    ext = filepath.suffix.lower()
    return FILE_TYPE_MAP.get(ext, "binary" if ext in BINARY_EXTENSIONS else "text")


def _is_binary_file(filepath: Path) -> bool:
    """Check if file should be treated as binary."""
    ext = filepath.suffix.lower()
    return ext in BINARY_EXTENSIONS


def _format_size(size_bytes: int) -> str:
    """Format file size in human-readable format."""
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def _get_file_info(filepath: Path, workspace_path: Path) -> Dict[str, Any]:
    """Get metadata about a file."""
    try:
        stat_info = filepath.stat()
        relative_path = filepath.relative_to(workspace_path)
        return {
            "name": filepath.name,
            "relative_path": str(relative_path),
            "absolute_path": str(filepath),
            "size": stat_info.st_size,
            "size_human": _format_size(stat_info.st_size),
            "modified": datetime.fromtimestamp(stat_info.st_mtime).isoformat(),
            "type": _get_file_type(filepath),
            "is_binary": _is_binary_file(filepath),
            "readable": os.access(filepath, os.R_OK),
        }
    except OSError as e:
        return {
            "name": filepath.name,
            "error": str(e),
        }


def register_workspace_file_tools(
    mcp: FastMCP,
    workspace_manager: Optional["WorkspaceManager"] = None,
    scp_host: str = "aurora",
) -> None:
    """Register workspace file access tools.

    Args:
        mcp: FastMCP server instance
        workspace_manager: Workspace manager for validation
        scp_host: Hostname to use in scp paths (default: "aurora")
    """
    if workspace_manager is None:
        logger.warning("Workspace manager not available, file tools disabled")
        return

    @mcp.tool()
    def list_workspace_files(
        workspace_id: str,
        pattern: str = "*",
        include_subdirs: bool = True,
        max_files: int = DEFAULT_MAX_LIST_FILES,
    ) -> Dict[str, Any]:
        """
        List files in a job workspace directory.

        Use this tool to discover what files exist in a workspace after a job
        has completed. Returns file metadata including paths suitable for scp.

        Args:
            workspace_id: The workspace ID (from build_*_submit_script)
            pattern: Glob pattern to filter files (default: "*" for all)
                     Examples: "*.hdf5", "*.log", "pepper_*"
            include_subdirs: Whether to search subdirectories (default: True)
            max_files: Maximum number of files to return (default: 1000)

        Returns:
            Dictionary with:
            - workspace_id: The workspace ID
            - workspace_path: Absolute path to workspace
            - scp_prefix: Prefix for scp commands (e.g., "aurora:/path/to/workspace")
            - files: List of file info dicts with name, path, size, type, etc.
            - total_files: Number of files found
            - total_size: Total size of all files
            - truncated: Whether file list was truncated due to max_files

        Example:
            # List all HDF5 files in workspace
            list_workspace_files(workspace_id="abc123", pattern="*.hdf5")

            # Then use scp locally:
            # scp aurora:/path/to/workspace/events.hdf5 ./
        """
        # Validate workspace exists
        workspace_path = _validate_workspace_path(workspace_manager, workspace_id)
        if workspace_path is None:
            return {
                "error": f"Workspace '{workspace_id}' not found",
                "status": "failed",
            }

        if not workspace_path.exists():
            return {
                "error": f"Workspace path does not exist: {workspace_path}",
                "status": "failed",
            }

        logger.info(f"Listing files in workspace {workspace_id}: {workspace_path}")

        # Collect files matching pattern
        files: List[Dict[str, Any]] = []
        total_size = 0
        truncated = False

        try:
            if include_subdirs:
                # Recursive glob
                all_files = list(workspace_path.rglob("*"))
            else:
                # Non-recursive
                all_files = list(workspace_path.glob("*"))

            # Filter to files only (not directories) and apply pattern
            for filepath in all_files:
                if not filepath.is_file():
                    continue

                # Apply pattern filter
                if not fnmatch.fnmatch(filepath.name, pattern):
                    continue

                if len(files) >= max_files:
                    truncated = True
                    break

                file_info = _get_file_info(filepath, workspace_path)
                files.append(file_info)
                if "size" in file_info:
                    total_size += file_info["size"]

        except OSError as e:
            return {
                "error": f"Error listing files: {e}",
                "status": "failed",
            }

        # Sort by name
        files.sort(key=lambda f: f.get("relative_path", f.get("name", "")))

        return {
            "workspace_id": workspace_id,
            "workspace_path": str(workspace_path),
            "scp_prefix": f"{scp_host}:{workspace_path}",
            "files": files,
            "total_files": len(files),
            "total_size": total_size,
            "total_size_human": _format_size(total_size),
            "truncated": truncated,
            "pattern": pattern,
            "status": "success",
        }

    @mcp.tool()
    def read_workspace_file(
        workspace_id: str,
        filename: str,
        encoding: str = "auto",
        max_size_mb: float = DEFAULT_MAX_READ_SIZE_MB,
        offset: int = 0,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Read the contents of a file from a workspace.

        For text files, returns the content as a string. For binary files,
        returns base64-encoded content. Use this to view logs, check output,
        or retrieve small data files.

        Args:
            workspace_id: The workspace ID
            filename: Relative path to file within workspace
                      (e.g., "pepper_stdout.log" or "subdir/data.txt")
            encoding: "auto" (detect), "text", or "base64" for binary
            max_size_mb: Maximum file size to read (default: 10 MB)
            offset: Line offset for text files, byte offset for binary (default: 0)
            limit: Max lines for text, max bytes for binary (default: None = all)

        Returns:
            Dictionary with:
            - content: File contents (string or base64)
            - filename: The validated filename
            - path: Absolute path to file
            - scp_path: Path for scp command
            - size: File size in bytes
            - encoding: "text" or "base64"
            - truncated: Whether content was truncated
            - lines_read: Number of lines (for text files)

        Security:
            - Path traversal is blocked (../ rejected)
            - Only files within workspace are accessible
            - Size limits prevent memory exhaustion

        Example:
            # Read a log file
            read_workspace_file(workspace_id="abc123", filename="pepper_stdout.log")

            # Read with line limit
            read_workspace_file(workspace_id="abc123", filename="output.log", limit=100)
        """
        # Validate workspace exists
        workspace_path = _validate_workspace_path(workspace_manager, workspace_id)
        if workspace_path is None:
            return {
                "error": f"Workspace '{workspace_id}' not found",
                "status": "failed",
            }

        # Validate filename (security check)
        if not _validate_filename(filename):
            return {
                "error": f"Invalid filename: '{filename}'. Path traversal not allowed.",
                "status": "failed",
            }

        # Construct full path and verify it's within workspace
        filepath = workspace_path / filename
        try:
            filepath = filepath.resolve()
            # Ensure resolved path is still within workspace
            filepath.relative_to(workspace_path.resolve())
        except ValueError:
            return {
                "error": f"Access denied: file is outside workspace",
                "status": "failed",
            }

        if not filepath.exists():
            return {
                "error": f"File not found: '{filename}'",
                "status": "failed",
            }

        if not filepath.is_file():
            return {
                "error": f"Not a file: '{filename}'",
                "status": "failed",
            }

        # Check file size
        file_size = filepath.stat().st_size
        max_size_bytes = int(max_size_mb * 1024 * 1024)

        if file_size > max_size_bytes:
            return {
                "error": f"File too large: {_format_size(file_size)} > {max_size_mb} MB limit",
                "hint": "Use get_workspace_file_path to get the scp path for direct download",
                "path": str(filepath),
                "scp_path": f"{scp_host}:{filepath}",
                "size": file_size,
                "status": "failed",
            }

        logger.info(f"Reading file from workspace {workspace_id}: {filename}")

        # Determine encoding
        is_binary = _is_binary_file(filepath)
        if encoding == "auto":
            use_binary = is_binary
        elif encoding == "base64":
            use_binary = True
        else:
            use_binary = False

        truncated = False
        lines_read = None

        try:
            if use_binary:
                # Binary mode - read bytes and encode as base64
                with open(filepath, "rb") as f:
                    if offset > 0:
                        f.seek(offset)
                    if limit:
                        data = f.read(limit)
                        truncated = f.read(1) != b""
                    else:
                        data = f.read()
                content = base64.b64encode(data).decode("ascii")
                actual_encoding = "base64"
            else:
                # Text mode - read lines
                with open(filepath, "r", errors="replace") as f:
                    if offset > 0:
                        # Skip offset lines
                        for _ in range(offset):
                            if f.readline() == "":
                                break

                    if limit:
                        lines = []
                        for _ in range(limit):
                            line = f.readline()
                            if line == "":
                                break
                            lines.append(line)
                        # Check if there's more
                        truncated = f.readline() != ""
                        content = "".join(lines)
                        lines_read = len(lines)
                    else:
                        content = f.read()
                        lines_read = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
                actual_encoding = "text"

        except OSError as e:
            return {
                "error": f"Error reading file: {e}",
                "status": "failed",
            }

        result: Dict[str, Any] = {
            "content": content,
            "filename": filename,
            "path": str(filepath),
            "scp_path": f"{scp_host}:{filepath}",
            "size": file_size,
            "size_human": _format_size(file_size),
            "encoding": actual_encoding,
            "truncated": truncated,
            "status": "success",
        }

        if lines_read is not None:
            result["lines_read"] = lines_read

        return result

    @mcp.tool()
    def get_workspace_file_path(
        workspace_id: str,
        filename: str,
        compute_checksum: bool = False,
    ) -> Dict[str, Any]:
        """
        Get the path and metadata for a file in a workspace.

        Use this to get the full path for scp/rsync commands when you need
        to transfer files to your local machine. Does not read file contents.

        Args:
            workspace_id: The workspace ID
            filename: Relative path to file within workspace
            compute_checksum: Whether to compute SHA256 checksum (default: False)

        Returns:
            Dictionary with:
            - path: Absolute path to file
            - scp_path: Path for scp command (e.g., "aurora:/path/to/file")
            - rsync_path: Path for rsync command
            - exists: Whether file exists
            - size: File size in bytes
            - type: File type (hdf5, log, text, etc.)
            - checksum: SHA256 hash (if compute_checksum=True)

        Example:
            # Get path for scp
            result = get_workspace_file_path(workspace_id="abc123", filename="events.hdf5")
            # Then on laptop: scp aurora:/path/to/events.hdf5 ./
        """
        # Validate workspace exists
        workspace_path = _validate_workspace_path(workspace_manager, workspace_id)
        if workspace_path is None:
            return {
                "error": f"Workspace '{workspace_id}' not found",
                "status": "failed",
            }

        # Validate filename (security check)
        if not _validate_filename(filename):
            return {
                "error": f"Invalid filename: '{filename}'. Path traversal not allowed.",
                "status": "failed",
            }

        # Construct full path and verify it's within workspace
        filepath = workspace_path / filename
        try:
            filepath = filepath.resolve()
            # Ensure resolved path is still within workspace
            filepath.relative_to(workspace_path.resolve())
        except ValueError:
            return {
                "error": f"Access denied: file is outside workspace",
                "status": "failed",
            }

        exists = filepath.exists() and filepath.is_file()

        result: Dict[str, Any] = {
            "filename": filename,
            "path": str(filepath),
            "scp_path": f"{scp_host}:{filepath}",
            "rsync_path": f"{scp_host}:{filepath}",
            "exists": exists,
            "workspace_id": workspace_id,
            "workspace_path": str(workspace_path),
            "status": "success",
        }

        if exists:
            stat_info = filepath.stat()
            result.update({
                "size": stat_info.st_size,
                "size_human": _format_size(stat_info.st_size),
                "modified": datetime.fromtimestamp(stat_info.st_mtime).isoformat(),
                "type": _get_file_type(filepath),
                "is_binary": _is_binary_file(filepath),
                "readable": os.access(filepath, os.R_OK),
            })

            if compute_checksum:
                try:
                    sha256 = hashlib.sha256()
                    with open(filepath, "rb") as f:
                        for chunk in iter(lambda: f.read(8192), b""):
                            sha256.update(chunk)
                    result["checksum"] = sha256.hexdigest()
                    result["checksum_algorithm"] = "sha256"
                except OSError as e:
                    result["checksum_error"] = str(e)

        logger.info(f"File path request for workspace {workspace_id}: {filename} (exists={exists})")

        return result

    @mcp.tool()
    def get_workspace_file_info(
        workspace_id: str,
        filename: str,
    ) -> Dict[str, Any]:
        """
        Get detailed metadata about a file without reading its contents.

        Use this for a quick check of file existence, size, and type before
        deciding whether to read or download.

        Args:
            workspace_id: The workspace ID
            filename: Relative path to file within workspace

        Returns:
            Dictionary with:
            - exists: Whether file exists
            - size: File size in bytes
            - size_human: Human-readable size
            - modified: Last modification timestamp
            - type: File type (hdf5, log, text, etc.)
            - is_binary: Whether file is binary
            - readable: Whether file is readable
            - permissions: File permissions string

        Example:
            # Check if output file exists and how large it is
            get_workspace_file_info(workspace_id="abc123", filename="events.hdf5")
        """
        # Validate workspace exists
        workspace_path = _validate_workspace_path(workspace_manager, workspace_id)
        if workspace_path is None:
            return {
                "error": f"Workspace '{workspace_id}' not found",
                "status": "failed",
            }

        # Validate filename (security check)
        if not _validate_filename(filename):
            return {
                "error": f"Invalid filename: '{filename}'. Path traversal not allowed.",
                "status": "failed",
            }

        # Construct full path and verify it's within workspace
        filepath = workspace_path / filename
        try:
            filepath = filepath.resolve()
            # Ensure resolved path is still within workspace
            filepath.relative_to(workspace_path.resolve())
        except ValueError:
            return {
                "error": f"Access denied: file is outside workspace",
                "status": "failed",
            }

        result: Dict[str, Any] = {
            "filename": filename,
            "path": str(filepath),
            "workspace_id": workspace_id,
            "status": "success",
        }

        if not filepath.exists():
            result["exists"] = False
            return result

        if not filepath.is_file():
            result["exists"] = False
            result["is_directory"] = filepath.is_dir()
            return result

        try:
            stat_info = filepath.stat()
            mode = stat_info.st_mode

            result.update({
                "exists": True,
                "size": stat_info.st_size,
                "size_human": _format_size(stat_info.st_size),
                "modified": datetime.fromtimestamp(stat_info.st_mtime).isoformat(),
                "created": datetime.fromtimestamp(stat_info.st_ctime).isoformat(),
                "type": _get_file_type(filepath),
                "is_binary": _is_binary_file(filepath),
                "readable": os.access(filepath, os.R_OK),
                "writable": os.access(filepath, os.W_OK),
                "permissions": stat.filemode(mode),
            })
        except OSError as e:
            result["error"] = str(e)
            result["exists"] = True  # File exists but we can't stat it

        logger.info(f"File info request for workspace {workspace_id}: {filename}")

        return result

    logger.info("Registered workspace file access tools")
