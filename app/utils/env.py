"""Environment validation utilities for the Whisper GUI backend."""

from __future__ import annotations

import os
import shutil
from typing import Iterable, Tuple


class EnvironmentValidationError(RuntimeError):
    """Raised when required runtime dependencies are missing or invalid."""


def _binary_check_errors(binaries: Iterable[Tuple[str, str]]) -> list[str]:
    errors: list[str] = []
    for binary, install_hint in binaries:
        if shutil.which(binary) is None:
            errors.append(
                f"Команда '{binary}' не найдена. {install_hint}".strip()
            )
    return errors


def _disk_space_error(path: str, min_free_gb: float) -> str | None:
    try:
        usage = shutil.disk_usage(path)
    except FileNotFoundError:
        return (
            "Невозможно определить свободное место: "
            f"путь '{os.path.abspath(path)}' не существует."
        )

    free_gb = usage.free / (1024 ** 3)
    if free_gb < min_free_gb:
        return (
            "Недостаточно свободного места на диске: "
            f"доступно {free_gb:.1f} ГБ, требуется не менее {min_free_gb:.1f} ГБ."
        )
    return None


def validate_environment(
    *,
    binaries: Iterable[Tuple[str, str]] | None = None,
    disk_path: str = ".",
    min_free_gb: float = 2.0,
) -> None:
    """Validate the runtime environment.

    Args:
        binaries: A sequence of tuples where the first element is the command to
            look for in ``PATH`` and the second element is a short installation
            hint shown to the user when the binary is missing. When ``None``, a
            default set of required utilities is used.
        disk_path: Path that should reside on the target filesystem. Defaults to
            the current working directory.
        min_free_gb: Minimum amount of free disk space (in gigabytes) required
            to run the application reliably.

    Raises:
        EnvironmentValidationError: If one or more checks fail.
    """

    default_binaries = (
        ("ffmpeg", "Установите ffmpeg и убедитесь, что он доступен в PATH."),
        (
            "yt-dlp",
            "Установите yt-dlp (pip install yt-dlp) и убедитесь в его доступности в PATH.",
        ),
    )
    binaries = binaries or default_binaries

    errors = _binary_check_errors(binaries)

    disk_error = _disk_space_error(disk_path, min_free_gb)
    if disk_error:
        errors.append(disk_error)

    if errors:
        joined = "\n".join(errors)
        raise EnvironmentValidationError(
            "Ошибки проверки окружения:\n" f"{joined}"
        )


__all__ = ["EnvironmentValidationError", "validate_environment"]
