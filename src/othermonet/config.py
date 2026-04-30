"""Path configuration for the Inbox and Processed Archive.

All paths are resolvable at runtime via environment variables so tests can
point at temp directories without monkey-patching module globals.
"""

import os
from pathlib import Path


def inbox_dir() -> Path:
    return Path(os.environ.get("OTHERMONET_INBOX", "inbox"))


def archive_dir() -> Path:
    return Path(os.environ.get("OTHERMONET_ARCHIVE", "processed"))
