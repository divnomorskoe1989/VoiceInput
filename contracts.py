from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass(slots=True)
class TranscriptEvent:
    text: str
    is_final: bool
    source: str = "stt"


@dataclass(slots=True)
class InsertResult:
    strategy: str
    executed: bool
    success: bool
    clipboard_consumed: bool = False
    latency_ms: float = 0.0


@dataclass(slots=True)
class SessionStats:
    duration_sec: float = 0.0
    fragments_inserted: int = 0
    chars_inserted: int = 0
    window_hint: str = "default"
    mode: str = "realtime"
    status: str = "OK"
    metadata: Dict[str, str] = field(default_factory=dict)
