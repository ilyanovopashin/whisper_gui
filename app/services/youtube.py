"""Utilities for working with YouTube audio downloads.

This module exposes :class:`YoutubeAudioService`, a small wrapper around
``yt_dlp.YoutubeDL`` that keeps all downloaded files under
``app/storage/downloads`` and makes sure we only fetch audio streams.

It also exposes helpers for storing local files in ``app/storage/uploads`` so
that the rest of the application does not need to deal with user supplied
paths directly.
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List

import yt_dlp
from yt_dlp.utils import DownloadError, sanitize_filename


DEFAULT_MAX_AGE_SECONDS = 24 * 60 * 60  # one day


@dataclass
class DownloadReport:
    """Detailed information about an attempted download."""

    requested_url: str
    downloaded_files: List[Path]
    free_space_before: int
    free_space_after: int
    info: Dict[str, object]


class YoutubeAudioService:
    """High-level helper for working with :mod:`yt_dlp` audio downloads."""

    def __init__(
        self,
        download_root: Path | str = Path("app/storage/downloads"),
        upload_root: Path | str = Path("app/storage/uploads"),
        *,
        max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
    ) -> None:
        self.download_root = Path(download_root)
        self.upload_root = Path(upload_root)
        self.max_age_seconds = max_age_seconds
        self.download_root.mkdir(parents=True, exist_ok=True)
        self.upload_root.mkdir(parents=True, exist_ok=True)

        self._base_opts: Dict[str, object] = {
            "format": "bestaudio/best",
            "outtmpl": str(self.download_root / "%(title)s.%(ext)s"),
            "paths": {"home": str(self.download_root)},
            "restrictfilenames": False,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "skip_download": False,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _create_downloader(self, **overrides: object) -> yt_dlp.YoutubeDL:
        opts = {**self._base_opts, **overrides}
        return yt_dlp.YoutubeDL(opts)

    def _normalize_downloads(self, info: Dict[str, object]) -> List[Path]:
        """Ensure downloaded filenames are normalized and sanitized."""

        normalized_paths: List[Path] = []
        requested_downloads: Iterable[Dict[str, object]] = info.get(
            "requested_downloads", []
        )  # type: ignore[assignment]
        for entry in requested_downloads:
            raw_path = entry.get("filepath")
            if not raw_path:
                continue
            filepath = Path(str(raw_path))
            normalized_name = self.normalize_filename(filepath.name)
            normalized_path = filepath.with_name(normalized_name)
            if filepath != normalized_path:
                if normalized_path.exists():
                    normalized_path.unlink()
                filepath.rename(normalized_path)
            normalized_paths.append(normalized_path)
        return normalized_paths

    def _cleanup_empty_directories(self, root: Path) -> None:
        for directory in sorted({p.parent for p in root.rglob("*")}, reverse=True):
            if directory == root:
                continue
            if directory.exists() and not any(directory.iterdir()):
                directory.rmdir()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def check_url_available(self, url: str) -> Dict[str, object]:
        """Return the metadata for *url* without downloading anything."""

        try:
            with self._create_downloader(skip_download=True) as downloader:
                return downloader.extract_info(url, download=False)
        except DownloadError as exc:
            raise ValueError(f"URL is not available: {url}") from exc

    def get_free_space(self) -> int:
        """Return the free space (in bytes) available under the download root."""

        usage = shutil.disk_usage(self.download_root)
        return usage.free

    def clean_old_downloads(self) -> List[Path]:
        """Remove download files that are older than ``max_age_seconds``."""

        removed: List[Path] = []
        threshold = time.time() - self.max_age_seconds
        for file in self.download_root.rglob("*"):
            if file.is_file() and file.stat().st_mtime < threshold:
                file.unlink(missing_ok=True)
                removed.append(file)
        self._cleanup_empty_directories(self.download_root)
        return removed

    def normalize_filename(self, filename: str) -> str:
        """Return a sanitized filename safe for the local filesystem."""

        return sanitize_filename(filename, restricted=True)

    def download_audio(self, url: str) -> DownloadReport:
        """Download *url* as audio while enforcing service policies."""

        metadata = self.check_url_available(url)
        free_before = self.get_free_space()
        self.clean_old_downloads()

        with self._create_downloader() as downloader:
            info = downloader.extract_info(url, download=True)

        downloaded_files = self._normalize_downloads(info)
        free_after = self.get_free_space()

        return DownloadReport(
            requested_url=url,
            downloaded_files=downloaded_files,
            free_space_before=free_before,
            free_space_after=free_after,
            info=metadata,
        )

    def store_local_file(self, source: Path | str) -> Path:
        """Copy *source* to the upload directory and return the new path."""

        source_path = Path(source).expanduser().resolve(strict=True)
        sanitized_name = self.normalize_filename(source_path.name)
        destination = self.upload_root / sanitized_name
        if source_path == destination:
            return destination
        shutil.copy2(source_path, destination)
        return destination

    def stream_local_file(self, source: Path | str, chunk_size: int = 8192) -> Iterable[bytes]:
        """Yield chunks of *source* after copying it into the upload storage."""

        stored_path = self.store_local_file(source)
        with stored_path.open("rb") as handle:
            while chunk := handle.read(chunk_size):
                yield chunk


__all__ = ["DownloadReport", "YoutubeAudioService"]
