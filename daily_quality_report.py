from __future__ import annotations

from datetime import datetime
from pathlib import Path

from quality_report import build_quality_summary


def generate_daily_report(log_path: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = build_quality_summary(log_path)
    file_name = f"daily_quality_report_{datetime.now().strftime('%Y%m%d')}.txt"
    report_path = output_dir / file_name
    report_path.write_text(
        "\n".join(
            [
                f"sessions={summary.sessions}",
                f"total_duration_sec={summary.total_duration_sec:.2f}",
                f"total_fragments={summary.total_fragments}",
                f"total_chars={summary.total_chars}",
                f"avg_chars_per_session={summary.avg_chars_per_session:.2f}",
            ]
        ),
        encoding="utf-8",
    )
    return report_path


if __name__ == "__main__":
    report = generate_daily_report(Path("tmp/voice_input_recovered.log"), Path("tmp"))
    print(report)
