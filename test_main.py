import sys

import main as recovered_main


def test_hotkey_text_conversion_for_pynput():
    assert recovered_main._to_pynput_hotkey("ctrl+win") == "<ctrl>+<cmd>"
    assert recovered_main._to_pynput_hotkey("Control + Alt + Shift") == "<ctrl>+<alt>+<shift>"


def test_modifier_only_hotkey_detection():
    assert recovered_main._is_modifier_only_hotkey("ctrl+win") is True
    assert recovered_main._is_modifier_only_hotkey("ctrl+shift+a") is False


def test_modifier_match_for_ctrl_win_hotkey():
    assert recovered_main._modifiers_match_hotkey({"ctrl", "cmd"}, "ctrl+win") is True
    assert recovered_main._modifiers_match_hotkey({"ctrl"}, "ctrl+win") is False


def test_main_once_deepgram_without_key_returns_config_error(monkeypatch, capsys):
    monkeypatch.setenv("DEEPGRAM_API_KEY", "")
    monkeypatch.setattr(sys, "argv", ["main.py", "--once", "--backend", "deepgram"])

    code = recovered_main.main()
    output = capsys.readouterr().out

    assert code == 2
    assert "Configuration error: DEEPGRAM_API_KEY is required" in output


def test_main_once_mock_returns_success(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        ["main.py", "--once", "--backend", "mock", "--simulate-text", "smoke"],
    )

    code = recovered_main.main()
    output = capsys.readouterr().out

    assert code == 0
    assert "Session finished:" in output
