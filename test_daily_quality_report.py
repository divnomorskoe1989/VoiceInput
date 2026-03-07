from pathlib import Path

from daily_quality_report import generate_daily_report


def test_daily_quality_report_creates_file(tmp_path: Path):
    log_file = tmp_path / "app.log"
    log_file.write_text(
        "SESSION_DIAG | duration=1.0s | fragments=1 | chars=5 | interim_used=no | mode=realtime | window=default | strategy=ctrl_v | status=OK",
        encoding="utf-8",
    )

    report_path = generate_daily_report(log_file, tmp_path)

    assert report_path.exists()
    content = report_path.read_text(encoding="utf-8")
    assert "sessions=1" in content
    assert "total_chars=5" in content
