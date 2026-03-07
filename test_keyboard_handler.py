from keyboard_handler import HotkeyHandler


def test_hotkey_handler_triggers_callback():
    hit = {"value": False}
    handler = HotkeyHandler("ctrl+win", debounce_ms=0)
    handler.set_callback(lambda: hit.__setitem__("value", True))

    accepted = handler.trigger()

    assert accepted is True
    assert hit["value"] is True


def test_hotkey_handler_debounce_ignores_quick_duplicate():
    now = {"value": 100.0}
    hit = {"count": 0}

    def time_fn() -> float:
        return now["value"]

    handler = HotkeyHandler("ctrl+win", debounce_ms=250, time_fn=time_fn)
    handler.set_callback(lambda: hit.__setitem__("count", hit["count"] + 1))

    assert handler.trigger() is True
    now["value"] = 100.100
    assert handler.trigger() is False
    now["value"] = 100.500
    assert handler.trigger() is True

    assert hit["count"] == 2


def test_hotkey_handler_callback_exception_is_handled():
    handler = HotkeyHandler("ctrl+win", debounce_ms=0)

    def boom() -> None:
        raise RuntimeError("callback failed")

    handler.set_callback(boom)
    assert handler.trigger() is False
