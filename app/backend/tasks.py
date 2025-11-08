"""Background task dispatcher for transcription jobs."""
from __future__ import annotations

import asyncio
import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from .pipeline import TranscriptionPipeline


ISO_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


class JobStatus:
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class JobState(BaseModel):
    """Public facing job state."""

    id: str
    status: str = Field(default=JobStatus.QUEUED)
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    log: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    result_path: Optional[str] = None
    error: Optional[str] = None

    class Config:
        json_encoders = {datetime: lambda dt: dt.strftime(ISO_FORMAT)}


@dataclass
class TaskSpec:
    job_id: str
    source_path: Optional[Path] = None
    source_url: Optional[str] = None


class HistoryRepository:
    """Persist job history in a JSON file."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.write_text("[]", encoding="utf-8")

    def append(self, record: Dict[str, Any]) -> None:
        with self._lock:
            history = json.loads(self._path.read_text(encoding="utf-8"))
            history.append(record)
            self._path.write_text(json.dumps(history, indent=2), encoding="utf-8")

    def prune(self, keep_ids: Iterable[str]) -> None:
        keep = set(keep_ids)
        with self._lock:
            history = json.loads(self._path.read_text(encoding="utf-8"))
            filtered = [entry for entry in history if entry.get("id") in keep]
            self._path.write_text(json.dumps(filtered, indent=2), encoding="utf-8")


class TaskManager:
    """Coordinate background transcription jobs."""

    def __init__(
        self,
        *,
        base_dir: Optional[Path] = None,
        retention: timedelta = timedelta(days=7),
        cleanup_interval: timedelta = timedelta(hours=6),
    ) -> None:
        self.base_dir = base_dir or Path.cwd()
        self.data_dir = self.base_dir / "data"
        self.upload_dir = self.data_dir / "uploads"
        self.results_dir = self.data_dir / "results"
        self.logs_dir = self.data_dir / "logs"
        self.history_path = self.data_dir / "history.json"

        for directory in (self.upload_dir, self.results_dir, self.logs_dir):
            directory.mkdir(parents=True, exist_ok=True)

        self.retention = retention
        self.cleanup_interval = cleanup_interval

        self._states: Dict[str, JobState] = {}
        self._state_lock = threading.Lock()

        self._history = HistoryRepository(self.history_path)

        self._hf_token = self._load_hf_token()
        self._secret_values = [self._hf_token] if self._hf_token else []

        self._pipeline = TranscriptionPipeline(hf_token=self._hf_token)

        self._loop = asyncio.new_event_loop()
        self._queue_ready = threading.Event()
        self._worker_thread = threading.Thread(target=self._run_loop, daemon=True)
        self._worker_thread.start()
        self._queue_ready.wait()

        self._cleanup_stop = threading.Event()
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_scheduler, daemon=True
        )
        self._cleanup_thread.start()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def create_job_from_upload(self, filename: str, data: bytes) -> str:
        job_id = self._create_job_id()
        source_path = self.upload_dir / f"{job_id}_{filename}"
        source_path.write_bytes(data)
        self._register_job(job_id)
        self._enqueue(TaskSpec(job_id=job_id, source_path=source_path))
        return job_id

    def create_job_from_url(self, url: str) -> str:
        job_id = self._create_job_id()
        self._register_job(job_id)
        self._enqueue(TaskSpec(job_id=job_id, source_url=url))
        return job_id

    def get_job_state(self, job_id: str) -> Optional[JobState]:
        with self._state_lock:
            state = self._states.get(job_id)
            return state.copy(deep=True) if state else None

    def get_job_result(self, job_id: str) -> Optional[Path]:
        state = self.get_job_state(job_id)
        if not state or not state.result_path:
            return None
        result_path = Path(state.result_path)
        return result_path if result_path.exists() else None

    def cleanup_old_artifacts(self) -> None:
        cutoff = datetime.now(timezone.utc) - self.retention
        removed_ids: List[str] = []
        with self._state_lock:
            for job_id, state in list(self._states.items()):
                if state.updated_at < cutoff:
                    removed_ids.append(job_id)
                    self._remove_job_files(job_id, state)
                    del self._states[job_id]

        if removed_ids:
            self._history.prune(self._states.keys())

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _register_job(self, job_id: str) -> None:
        with self._state_lock:
            self._states[job_id] = JobState(id=job_id)

    def _create_job_id(self) -> str:
        return uuid4().hex

    def _enqueue(self, spec: TaskSpec) -> None:
        asyncio.run_coroutine_threadsafe(self._queue.put(spec), self._loop)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._queue = asyncio.Queue()
        self._loop.create_task(self._worker())
        self._queue_ready.set()
        self._loop.run_forever()

    async def _worker(self) -> None:
        while True:
            spec: TaskSpec = await self._queue.get()
            await self._process(spec)
            self._queue.task_done()

    async def _process(self, spec: TaskSpec) -> None:
        await asyncio.to_thread(self._execute, spec)

    def _execute(self, spec: TaskSpec) -> None:
        job_id = spec.job_id
        self._update_state(job_id, status=JobStatus.PROCESSING, progress=0.05)
        self._log(job_id, "Job accepted by worker")

        try:
            source_path = self._prepare_source(job_id, spec)
            result_path = self.results_dir / f"{job_id}.txt"

            def progress_callback(value: float) -> None:
                self._update_state(job_id, progress=max(min(value, 1.0), 0.0))

            def log_callback(message: str) -> None:
                self._log(job_id, message)

            self._log(job_id, "Starting transcription pipeline")
            self._pipeline.transcribe(
                source_path,
                result_path,
                progress_callback=progress_callback,
                log_callback=log_callback,
            )

            self._update_state(
                job_id,
                status=JobStatus.COMPLETED,
                progress=1.0,
                result_path=str(result_path),
            )
            self._log(job_id, "Job completed successfully")
            self._record_history(job_id)
        except Exception as exc:  # pragma: no cover - defensive
            self._update_state(
                job_id,
                status=JobStatus.FAILED,
                error=str(exc),
            )
            self._log(job_id, f"Job failed: {exc}")

    def _prepare_source(self, job_id: str, spec: TaskSpec) -> Path:
        if spec.source_path and spec.source_path.exists():
            return spec.source_path

        if spec.source_url:
            return self._download_source(job_id, spec.source_url)

        raise RuntimeError("No valid source provided for job")

    def _download_source(self, job_id: str, url: str) -> Path:
        import requests  # Local import to keep optional dependency

        self._log(job_id, f"Downloading media from {url}")
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        filename = url.split("/")[-1] or "downloaded_media"
        path = self.upload_dir / f"{job_id}_{filename}"
        path.write_bytes(response.content)
        self._log(job_id, f"Download finished: {path.name}")
        return path

    def _update_state(
        self,
        job_id: str,
        *,
        status: Optional[str] = None,
        progress: Optional[float] = None,
        result_path: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        with self._state_lock:
            state = self._states[job_id]
            if status is not None:
                state.status = status
            if progress is not None:
                state.progress = progress
            if result_path is not None:
                state.result_path = result_path
            if error is not None:
                state.error = error
            state.updated_at = datetime.now(timezone.utc)

    def _log(self, job_id: str, message: str) -> None:
        sanitized = self._sanitize(message)
        with self._state_lock:
            state = self._states[job_id]
            state.log.append(
                f"[{datetime.now(timezone.utc).strftime(ISO_FORMAT)}] {sanitized}"
            )
        log_file = self.logs_dir / f"{job_id}.log"
        with log_file.open("a", encoding="utf-8") as handler:
            handler.write(sanitized + "\n")

    def _sanitize(self, message: str) -> str:
        sanitized = message
        for secret in self._secret_values:
            if secret:
                sanitized = sanitized.replace(secret, "***")
        return sanitized

    def _record_history(self, job_id: str) -> None:
        state = self.get_job_state(job_id)
        if not state:
            return
        record = {
            "id": job_id,
            "status": state.status,
            "progress": state.progress,
            "result_path": state.result_path,
            "created_at": state.created_at.strftime(ISO_FORMAT),
            "updated_at": state.updated_at.strftime(ISO_FORMAT),
        }
        self._history.append(record)

    def _remove_job_files(self, job_id: str, state: JobState) -> None:
        if state.result_path:
            result = Path(state.result_path)
            if result.exists():
                result.unlink()
        upload_candidates = list(self.upload_dir.glob(f"{job_id}_*"))
        for path in upload_candidates:
            if path.exists():
                path.unlink()
        log_file = self.logs_dir / f"{job_id}.log"
        if log_file.exists():
            log_file.unlink()

    def _cleanup_scheduler(self) -> None:
        while not self._cleanup_stop.wait(self.cleanup_interval.total_seconds()):
            try:
                self.cleanup_old_artifacts()
            except Exception:  # pragma: no cover - defensive
                pass

    def shutdown(self) -> None:
        self._cleanup_stop.set()
        if self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._worker_thread.is_alive():
            self._worker_thread.join(timeout=1)
        if self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=1)

    def _load_hf_token(self) -> Optional[str]:
        env_path = self.base_dir / ".env"
        token = os.getenv("HF_TOKEN")
        if token:
            return token
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("HF_TOKEN="):
                    return line.split("=", 1)[1].strip()
        return None


__all__ = ["TaskManager", "JobState", "JobStatus"]
