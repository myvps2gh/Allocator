"""
Web interface and API for Allocator AI
"""

from .dashboard import create_app
from .api import create_api_blueprint

__all__ = [
    "create_app",
    "create_api_blueprint"
]
