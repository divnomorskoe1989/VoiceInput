from sound_notifier import SoundNotifier


def test_sound_notifier_start_and_stop_call_callback_with_signal():
    signals = []
    notifier = SoundNotifier(callback=lambda signal: signals.append(signal), enabled=False)

    notifier.notify_start()
    notifier.notify_stop()

    assert signals == ["start", "stop"]


def test_sound_notifier_legacy_callback_without_args_is_supported():
    count = {"value": 0}
    notifier = SoundNotifier(
        callback=lambda: count.__setitem__("value", count["value"] + 1),
        enabled=False,
    )

    notifier.notify()  # Backward-compatible alias for start sound.

    assert count["value"] == 1
