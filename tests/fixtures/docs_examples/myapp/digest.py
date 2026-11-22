"""File digests."""

import hashlib
from pathlib import Path


def sha256_of(path: Path) -> str:
    """Hex SHA-256 of a file's contents."""
    return hashlib.sha256(path.read_bytes()).hexdigest()
