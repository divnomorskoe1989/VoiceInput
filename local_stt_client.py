from __future__ import annotations

from stt_client import MockSTTClient


class LocalSTTClient(MockSTTClient):
    """Local fallback STT client for the recovered build."""
