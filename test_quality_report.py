from pathlib import Path

from quality_report import build_quality_summary


def test_quality_summary_parses_session_lines(tmp_path: Path):
    log_file = tmp_path / "app.log"
    log_file.write_text(
        "\n".join(
            [
                "SESSION_DIAG | duration=10.0s | fragments=2 | chars=50 | interim_used=no | mode=realtime | window=terminal | strategy=shift_insert | status=OK",
                "SESSION_DIAG | duration=4.5s | fragments=1 | chars=20 | interim_used=yes | mode=realtime | window=qt | strategy=ctrl_v | status=OK",
            ]
        ),
        encoding="utf-8",
    )

    summary = build_quality_summary(log_file)

    assert summary.sessions == 2
    assert summary.total_fragments == 3
    assert summary.total_chars == 70
    assert round(summary.total_duration_sec, 1) == 14.5
    assert round(summary.avg_chars_per_session, 1) == 35.0
