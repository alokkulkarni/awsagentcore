"""
Amazon Connect WebRTC Contact API package.

Exposes the FastAPI ``app`` object for import by Mangum (Lambda) or uvicorn
(container / local dev).
"""
from api.webrtc.app import app  # noqa: F401 – re-export for convenience

__all__ = ["app"]
