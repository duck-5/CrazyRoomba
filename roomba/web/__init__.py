"""
Web application subpackage for Roomba Cockpit and REST/WebSocket APIs.
"""

from .app import create_app, app, controller

__all__ = ["create_app", "app", "controller"]
