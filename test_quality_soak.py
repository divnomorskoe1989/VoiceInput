from text_inserter import TextInserter


def test_insert_soak_runs_many_iterations():
    inserter = TextInserter(strategy_handlers={"type_direct": lambda text: True})
    ok = 0
    for i in range(100):
        result = inserter.insert_text(f"line-{i}", window_title="terminal")
        if result.success:
            ok += 1
    assert ok == 100
