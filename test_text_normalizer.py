from text_normalizer import normalize_transcript_text


def test_normalize_transcript_text_removes_space_before_punctuation():
    assert normalize_transcript_text("Привет , мир !") == "Привет, мир!"


def test_normalize_transcript_text_adds_missing_space_after_punctuation():
    assert normalize_transcript_text("тест.следующий") == "тест. следующий"


def test_normalize_transcript_text_merges_auto_stop_phrase():
    assert normalize_transcript_text("авто стоп через пять секунд") == "автостоп через пять секунд"


def test_normalize_transcript_text_fixes_voiceinput_and_version():
    assert normalize_transcript_text("Voice Input версии 1. 0") == "VoiceInput версии 1.0"


def test_normalize_transcript_text_fixes_email_and_autostop_word():
    assert normalize_transcript_text("test example. com и autostop") == "test@example.com и автостоп"


def test_normalize_transcript_text_fixes_ctrl_combo_in_phrase_context():
    assert normalize_transcript_text("Сочетание Ctrl+V нужно") == "Сочетание Ctrl+Win нужно"
    assert normalize_transcript_text("Сочетание Ctrl V нужно") == "Сочетание Ctrl+Win нужно"
    assert normalize_transcript_text("запись стартует по Ctrl V") == "запись стартует по Ctrl+Win"


def test_normalize_transcript_text_fixes_specific_punctuation_flow():
    text = "версии 1. 0 скорость, пунктуацию и устойчивость Нужно распознать"
    assert normalize_transcript_text(text) == "версии 1.0: скорость, пунктуацию и устойчивость. Нужно распознать"


def test_normalize_transcript_text_converts_spoken_punctuation_words():
    text = "Проверка запятая точка вопрос восклицательный знак"
    assert normalize_transcript_text(text) == "Проверка,.?!"
