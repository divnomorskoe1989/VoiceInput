# Manual Test Checklist (VoiceInput Recovered)

Рабочая директория:
`C:\Users\Михаил\YandexDisk-mikhail.sklyarenko\vibecoding\Voiceinput\Voiceinput_recovered`

Быстрый запуск всего сценария (как раньше через `.bat`):

```bat
run_manual_test.bat
```

Поведение `run_manual_test.bat`:
- прогоняет 6 базовых проверок;
- при успехе автоматически запускает `run_live_listener.bat` для реального E2E;
- если нужен только прогон проверок без live-режима: `set SKIP_LIVE=1 && run_manual_test.bat`.

## 1) Базовая проверка запуска

```powershell
py main.py
```

Ожидаемо: сообщение
`VoiceInput recovered build is ready. Use --once for a simulated session.`

## 1.1) Живой режим горячей клавиши (Ctrl+Win)

```powershell
py main.py --listen-hotkey --backend deepgram
```

Ожидаемо:
- стартует listener и пишет подсказку в консоль;
- `Ctrl+Win` переключает start/stop записи;
- второй listener в параллель не запускается (если уже запущен, будет сообщение `Another VoiceInput listener is already running...`);
- стартовый сигнал звучит сразу при начале записи;
- стоп-сигнал звучит при ручном stop и при auto-stop;
- если 5 секунд нет голоса, срабатывает авто-стоп;
- текст вставляется в активное окно, где стоит курсор (Notepad/Telegram/терминал и т.п.);
- `Esc` завершает listener;
- в логе появляются события `HOTKEY`, `STEP`, `SOUND`, `MIC`, `DEEPGRAM`.

## 2) Smoke c mock backend

```powershell
py main.py --once --backend mock --simulate-text "manual mock check"
```

Ожидаемо:
- `Session finished: ...`
- в логе `tmp\voice_input_recovered.log` появляется `SESSION_DIAG | ... | status=OK`

## 3) Проверка валидации deepgram-конфига

```powershell
py -c "import sys; from stt_client import DeepgramSTTClient; \
try: DeepgramSTTClient(api_key='').connect(); sys.exit(1) \
except ValueError: print('deepgram_key_validation_ok')"
```

Ожидаемо:
- вывод `deepgram_key_validation_ok`

## 4) Живой deepgram прогон (ручной voice smoke)

```powershell
py main.py --listen-hotkey --backend deepgram
```

Ожидаемо:
- нажать `Ctrl+Win`, произнести длинную фразу;
- транскрипт появляется в терминале;
- при тишине >5 сек запись останавливается автоматически;
- в `tmp\voice_input_recovered.log` есть:
  - `STEP | ... | event=first_transcript_received`
  - `STEP | ... | event=first_insert_completed`
  - `STEP | ... | event=session_finished | ... | status=OK`
  - `SESSION_DIAG | ...`

## 5) Итог качества после ручных запусков

```powershell
py quality_report.py --log tmp/voice_input_recovered.log --output tmp/quality_report.json
Get-Content tmp/quality_report.json
```

Ожидаемо: корректный JSON со счётчиками `sessions`, `total_fragments`, `total_chars`.
