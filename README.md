# Whisper GUI

Интерактивное приложение и API для транскрибирования аудио с помощью WhisperX.

## Требования окружения

- Python 3.11+
- Установленные CLI-инструменты `ffmpeg` и `yt-dlp`
- Достаточное свободное место на диске (рекомендуется не менее 2 ГБ для временных файлов)

Перед запуском сервер выполняет проверку зависимостей (см. `app/utils/env.py`) и
выдаёт понятные сообщения об ошибках, если что-то отсутствует.

## Установка и запуск

1. Создайте виртуальное окружение и активируйте его.
2. Установите зависимости из `pyproject.toml` (например, `uv pip install -r pyproject.toml` или `pip install -e .[dev]`).
3. Заполните файл `.env` на основе `.env.example`.
4. Запустите сервер `uvicorn app.main:app --reload`.

## Установка PyTorch на macOS

PyTorch для macOS распространяется в виде отдельных колёс с поддержкой CPU или
MPS (Apple Silicon). Команды для установки:

### Intel/CPU

```bash
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
```

### Apple Silicon (MPS)

```bash
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
export PYTORCH_ENABLE_MPS_FALLBACK=1  # опционально, для автоматического переключения на CPU
```

Перед установкой убедитесь, что используете Python 3.11 и актуальную версию `pip`.
Дополнительные инструкции доступны на [pytorch.org](https://pytorch.org/get-started/locally/).

## Переменные окружения

Файл `.env` используется для настройки следующих параметров:

- `WHISPERX_MODEL` — модель по умолчанию (например, `medium.en`).
- `DATA_DIR` — каталог для временных и выходных файлов.
- `DATABASE_URL` — строка подключения к базе истории (например, SQLite `sqlite:///whisper.db`).
- `MIN_DISK_SPACE_GB` — минимальный запас свободного места (по умолчанию 2).
- `ENABLE_MPS` — установите в `true`, чтобы принудительно включить поддержку MPS.

Скопируйте `.env.example` и адаптируйте значения под своё окружение.
