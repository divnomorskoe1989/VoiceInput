from __future__ import annotations

import logging

from config import AppConfig
from local_stt_client import LocalSTTClient
from stt_client import DeepgramSTTClient, MockSTTClient, STTClient


def build_stt_client(config: AppConfig) -> STTClient:
    backend = (config.stt_backend or "mock").lower()
    if backend == "local":
        return LocalSTTClient()
    if backend == "mock":
        return MockSTTClient()
    if backend == "deepgram":
        return DeepgramSTTClient(
            api_key=config.deepgram_api_key,
            model=config.deepgram_model,
            language=config.deepgram_language,
            interim_results=config.interim_results,
            smart_format=config.smart_format,
            sample_rate=config.sample_rate,
            endpointing_ms=config.deepgram_endpointing_ms,
        )

    logging.getLogger("STTRouter").warning(
        "Unsupported STT backend '%s'. Falling back to mock backend.", backend
    )
    return MockSTTClient()
