"""Security utilities for path validation and input sanitization."""

# ============================================================================
# Standard Library Imports (alphabetical)
# ============================================================================
import re
from pathlib import Path
from typing import List, Optional

# ============================================================================
# Third-Party Imports (alphabetical, with version requirements)
# ============================================================================
# None

# ============================================================================
# Local Imports (grouped by package, alphabetical)
# ============================================================================
from core.logging import get_logger

logger = get_logger(__name__)


class SecurityValidator:
    """Security validation utilities."""

    # Dangerous path patterns
    DANGEROUS_PATTERNS = [
        r"\.\.",  # Path traversal
        r"//+",  # Multiple slashes
        r"~",  # Home directory expansion (should be resolved first)
    ]

    # Allowed file extensions for audio/video
    ALLOWED_EXTENSIONS = {
        # Audio
        ".mp3",
        ".m4a",
        ".aac",
        ".ogg",
        ".opus",
        ".flac",
        ".wav",
        ".aiff",
        ".alac",
        ".ape",
        ".wma",
        # Video
        ".mp4",
        ".mkv",
        ".webm",
        ".avi",
        ".mov",
        ".flv",
        ".wmv",
        ".m4v",
    }

    @staticmethod
    def validate_path(file_path: str, base_path: Optional[Path] = None) -> Optional[Path]:
        """
        Validate and sanitize a file path.

        Args:
            file_path: Path to validate
            base_path: Base directory to resolve relative paths against

        Returns:
            Resolved Path object if valid, None otherwise
        """
        if not file_path:
            logger.warning("Security: Empty file path provided")
            return None

        try:
            # Resolve to absolute path
            path = Path(file_path).expanduser().resolve()

            # Check for dangerous patterns in original path
            for pattern in SecurityValidator.DANGEROUS_PATTERNS:
                if re.search(pattern, file_path):
                    logger.warning("Security: Dangerous pattern detected in path: %s", file_path)
                    return None

            # Validate against base path if provided
            if base_path:
                base = Path(base_path).resolve()
                try:
                    # Check if path is within base directory
                    path.relative_to(base)
                except ValueError:
                    logger.warning("Security: Path outside base directory: %s", file_path)
                    return None

            # Check if file exists and is a regular file
            if not path.exists():
                logger.debug("Security: File does not exist: %s", path)
                return None

            if not path.is_file():
                logger.warning("Security: Path is not a regular file: %s", path)
                return None

            return path

        except (OSError, ValueError) as e:
            logger.warning("Security: Invalid path: %s (%s)", file_path, e)
            return None

    @staticmethod
    def validate_file_extension(file_path: str) -> bool:
        """
        Validate file extension against allowed list.

        Args:
            file_path: Path to validate

        Returns:
            True if extension is allowed, False otherwise
        """
        path = Path(file_path)
        ext = path.suffix.lower()

        if ext not in SecurityValidator.ALLOWED_EXTENSIONS:
            logger.warning("Security: Disallowed file extension: %s", ext)
            return False

        return True

    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """
        Sanitize a filename by removing dangerous characters.

        Args:
            filename: Filename to sanitize

        Returns:
            Sanitized filename
        """
        # Remove path separators
        filename = filename.replace("/", "").replace("\\", "")

        # Remove null bytes
        filename = filename.replace("\x00", "")

        # Remove control characters
        filename = "".join(c for c in filename if ord(c) >= 32 or c in "\t\n\r")

        # Limit length
        if len(filename) > 255:
            filename = filename[:255]

        return filename

    @staticmethod
    def validate_playlist_name(name: str) -> Optional[str]:
        """
        Validate and sanitize a playlist name.

        Args:
            name: Playlist name to validate

        Returns:
            Sanitized name if valid, None otherwise
        """
        if not name:
            return None

        # Remove dangerous characters
        sanitized = SecurityValidator.sanitize_filename(name)

        # Remove path separators
        sanitized = sanitized.replace("/", "").replace("\\", "")

        # Limit length
        if len(sanitized) > 100:
            sanitized = sanitized[:100]

        if not sanitized or sanitized.strip() == "":
            return None

        return sanitized

    @staticmethod
    def validate_dbus_path(path: str) -> bool:
        """
        Validate a D-Bus object path.

        Args:
            path: D-Bus path to validate

        Returns:
            True if path is valid, False otherwise
        """
        if not path:
            return False

        # D-Bus paths must start with /
        if not path.startswith("/"):
            return False

        # Check for valid characters (alphanumeric, underscore, slash)
        if not re.match(r"^/[a-zA-Z0-9_/]*$", path):
            logger.warning("Security: Invalid D-Bus path: %s", path)
            return False

        return True

    @staticmethod
    def validate_dbus_interface(interface: str) -> bool:
        """
        Validate a D-Bus interface name.

        Args:
            interface: Interface name to validate

        Returns:
            True if interface is valid, False otherwise
        """
        if not interface:
            return False

        # D-Bus interface names must match pattern: org.example.Interface
        if not re.match(r"^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)*$", interface):
            logger.warning("Security: Invalid D-Bus interface: %s", interface)
            return False

        return True
