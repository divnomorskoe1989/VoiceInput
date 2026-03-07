from text_inserter import TextInserter


def test_text_inserter_uses_strategy_chain():
    calls = []

    def fail(_text: str) -> bool:
        calls.append("ctrl_v")
        return False

    def ok(_text: str) -> bool:
        calls.append("type_direct")
        return True

    inserter = TextInserter(
        strategy_handlers={
            "ctrl_v": fail,
            "type_direct": ok,
        },
        enable_system_insertion=False,
    )

    # "default" chain is ["ctrl_v", "type_direct"]
    result = inserter.insert_text("hello", window_title="Notepad", window_class="Notepad")

    assert result.success is True
    assert result.strategy == "type_direct"
    assert calls == ["ctrl_v", "type_direct"]


def test_text_inserter_terminal_uses_type_direct():
    calls = []

    def ok(_text: str) -> bool:
        calls.append("type_direct")
        return True

    inserter = TextInserter(
        strategy_handlers={"type_direct": ok},
        enable_system_insertion=False,
    )

    result = inserter.insert_text("hello", window_title="Terminal", window_class="")

    assert result.success is True
    assert result.strategy == "type_direct"
    assert calls == ["type_direct"]


def test_text_inserter_empty_text_returns_no_op():
    inserter = TextInserter(enable_system_insertion=False)
    result = inserter.insert_text("")
    assert result.executed is False
    assert result.success is False
    assert result.strategy == "none"
