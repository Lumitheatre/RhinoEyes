"""RhinoEyes manifest manager package."""

from .manifest_manager import ManifestManager
from .constants import VERSION

__version__ = VERSION
__all__ = ["ManifestManager", "VERSION"]
