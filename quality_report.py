from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

SESSION_RE = re.compile(
    r"SESSION_DIAG \| duration=(?P<duration>[0-9.]+)s \| fragments=(?P<fragments>\d+) \| "
    r"chars=(?P<chars>\d+) \| interim_used=(?P<interim>yes|no) \| mode=(?P<mode>\w+) \| "
    r"window=(?P<window>\w+) \| strategy=(?P<strategy>[\w_]+) \| status=(?P<status>\w+)"
)


@dataclass(slots=True)
class QualitySummary:
    sessions: int
    total_duration_sec: float
    total_fragments: int
    total_chars: int
    avg_chars_per_session: float


def build_quality_summary(log_path: Path) -> QualitySummary:
    durations: list[float] = []
    fragments: list[int] = []
    chars: list[int] = []

    if not log_path.exists():
        return QualitySummary(0, 0.0, 0, 0, 0.0)

    for line in log_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = SESSION_RE.search(line)
        if not match:
            continue
        durations.append(float(match.group("duration")))
        fragments.append(int(match.group("fragments")))
        chars.append(int(match.group("chars")))

    sessions = len(durations)
    total_duration = sum(durations)
    total_fragments = sum(fragments)
    total_chars = sum(chars)
    avg_chars = (total_chars / sessions) if sessions else 0.0

    return QualitySummary(
        sessions=sessions,
        total_duration_sec=total_duration,
        total_fragments=total_fragments,
        total_chars=total_chars,
        avg_chars_per_session=avg_chars,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate quality report from VoiceInput logs")
    parser.add_argument(
        "--log",
        default="tmp/voice_input_recovered.log",
        help="Path to a log file with SESSION_DIAG lines",
    )
    parser.add_argument("--output", default="tmp/quality_report.json", help="Path to output JSON")
    args = parser.parse_args()

    summary = build_quality_summary(Path(args.log))
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(asdict(summary), ensure_ascii=False, indent=2), encoding="utf-8")
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
