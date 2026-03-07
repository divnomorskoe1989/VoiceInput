import pytest

from config import AppConfig
from stt_client import DeepgramSTTClient, MockSTTClient
from stt_router import build_stt_client


def test_router_fallbacks_to_mock_for_unknown_backend():
    cfg = AppConfig(stt_backend="unknown")
    client = build_stt_client(cfg)
    assert isinstance(client, MockSTTClient)


def test_router_returns_deepgram_and_requires_key():
    cfg = AppConfig(stt_backend="deepgram", deepgram_api_key="")
    client = build_stt_client(cfg)
    assert isinstance(client, DeepgramSTTClient)

    with pytest.raises(ValueError, match="DEEPGRAM_API_KEY is required"):
        client.connect()
