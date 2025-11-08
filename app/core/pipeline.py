"""Core transcription pipeline for Whisper GUI application.

This module provides the :class:`TranscriptionPipeline` which orchestrates the
conversion of heterogeneous audio sources into a uniform format, transcription
via `whisperx`, optional diarisation and persistence of the resulting artefacts
on disk.
"""
from __future__ import annotations

import contextlib
import dataclasses
import json
import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)


class PipelineError(RuntimeError):
    """Base error raised by the transcription pipeline."""


class InsufficientMemoryError(PipelineError):
    """Raised when the selected model cannot fit into available memory."""


class InvalidAuthTokenError(PipelineError):
    """Raised when the provided Hugging Face token is invalid."""


@dataclass(slots=True)
class LocalFile:
    """Represents a user supplied audio file stored locally."""

    path: Path

    def resolve(self, _workspace: Path) -> Path:
        if not self.path.exists():
            raise FileNotFoundError(f"Input file does not exist: {self.path!s}")
        return self.path


@dataclass(slots=True)
class YouTubeSource:
    """Represents an audio source retrieved from YouTube."""

    url: str

    def resolve(self, workspace: Path) -> Path:
        """Download and return the path to the extracted audio file."""
        try:
            import yt_dlp  # type: ignore
        except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency
            raise PipelineError(
                "YouTube audio support requires the 'yt_dlp' package to be installed"
            ) from exc

        output_template = workspace / "youtube.%(ext)s"
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": str(output_template),
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "wav",
                    "preferredquality": "192",
                }
            ],
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:  # pragma: no cover - network required
            logger.info("Downloading audio from %s", self.url)
            ydl.download([self.url])

        candidates = list(workspace.glob("youtube.*"))
        if not candidates:
            raise PipelineError("Failed to download audio from the provided YouTube URL")
        return candidates[0]


@dataclass(slots=True)
class ModelConfig:
    """Configuration required to load a Whisper model."""

    model_name: str = "large-v2"
    device: str = "cpu"
    compute_type: str = "float32"
    language: Optional[str] = None
    hf_token: Optional[str] = None
    batch_size: int = 16


@dataclass(slots=True)
class DiarizationConfig:
    """Configuration options for the diarization pipeline."""

    enabled: bool = False
    diarize_kwargs: Dict[str, Any] = dataclasses.field(default_factory=dict)


class TranscriptionPipeline:
    """High level orchestrator for WhisperX based transcription."""

    def __init__(
        self,
        source: Union[LocalFile, YouTubeSource],
        model_config: Optional[ModelConfig] = None,
        diarization_config: Optional[DiarizationConfig] = None,
        storage_dir: Union[str, Path] = Path("app/storage"),
    ) -> None:
        self.source = source
        self.model_config = model_config or ModelConfig()
        self.diarization_config = diarization_config or DiarizationConfig()
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Pipeline orchestration
    # ------------------------------------------------------------------
    def run(self) -> Dict[str, Path]:
        """Execute the complete transcription process.

        Returns
        -------
        dict
            A dictionary mapping artefact types (``json``, ``srt``, ``vtt``) to
            their corresponding file paths on disk.
        """

        with self._temporary_workspace() as workspace:
            raw_audio = self.source.resolve(workspace)
            prepared_audio, cleanup_paths = self.prepare_input(raw_audio, workspace)

            try:
                results = self._transcribe(prepared_audio)
                alignments = self._align(prepared_audio, results)
                diarization = self._diarize(prepared_audio)
                segments = self._assign_speakers(alignments["segments"], diarization)
                artefacts = self._persist_results(segments, alignments, prepared_audio)
            finally:
                self._cleanup(cleanup_paths)

        return artefacts

    # ------------------------------------------------------------------
    # Individual steps
    # ------------------------------------------------------------------
    def prepare_input(
        self, audio_path: Path, workspace: Path
    ) -> Tuple[Path, Iterable[Path]]:
        """Ensure the input audio is a mono 16kHz WAV file.

        Parameters
        ----------
        audio_path:
            The path to the raw audio.
        workspace:
            Directory that can be used for creating temporary files.

        Returns
        -------
        tuple[pathlib.Path, Iterable[pathlib.Path]]
            The processed audio path and a collection of temporary files to
            delete when processing completes.
        """

        audio_path = audio_path.resolve()
        cleanup: List[Path] = []

        if self._needs_conversion(audio_path):
            converted = workspace / "prepared.wav"
            self._convert_audio(audio_path, converted)
            cleanup.append(converted)
            return converted, cleanup

        return audio_path, cleanup

    def _needs_conversion(self, path: Path) -> bool:
        """Determine if the audio requires conversion."""

        probe_cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_name,sample_rate,channels",
            "-of",
            "json",
            str(path),
        ]

        try:
            completed = subprocess.run(
                probe_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
        except FileNotFoundError as exc:  # pragma: no cover - depends on environment
            raise PipelineError(
                "ffprobe is required to inspect audio files. Ensure ffmpeg is installed."
            ) from exc
        except subprocess.CalledProcessError as exc:
            logger.warning("ffprobe failed for %s: %s", path, exc.stderr.decode())
            return True

        data = json.loads(completed.stdout.decode() or "{}")
        streams = data.get("streams", [])
        if not streams:
            return True

        stream = streams[0]
        codec = stream.get("codec_name")
        sample_rate = int(stream.get("sample_rate", 0) or 0)
        channels = int(stream.get("channels", 0) or 0)

        return not (
            codec == "pcm_s16le" and sample_rate == 16000 and channels == 1
        )

    def _convert_audio(self, source: Path, destination: Path) -> None:
        """Convert audio to 16kHz mono WAV using ffmpeg."""

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(source),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(destination),
        ]

        try:
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except FileNotFoundError as exc:  # pragma: no cover - depends on environment
            raise PipelineError(
                "ffmpeg is required to convert audio files. Ensure it is installed."
            ) from exc
        except subprocess.CalledProcessError as exc:
            raise PipelineError(
                f"ffmpeg failed to convert audio: {exc.stderr.decode(errors='ignore')}"
            ) from exc

    def _transcribe(self, audio_path: Path) -> Dict[str, Any]:
        """Transcribe the provided audio using whisperx."""

        cfg = self.model_config
        try:
            import whisperx  # type: ignore
        except ModuleNotFoundError as exc:  # pragma: no cover - external dependency
            raise PipelineError(
                "The 'whisperx' package is required to run transcriptions."
            ) from exc

        try:
            model = whisperx.load_model(
                cfg.model_name,
                device=cfg.device,
                language=cfg.language,
                compute_type=cfg.compute_type,
                hf_token=cfg.hf_token,
            )
        except RuntimeError as exc:
            message = str(exc).lower()
            if "out of memory" in message:
                raise InsufficientMemoryError(message) from exc
            if "401" in message or "unauthorized" in message or "token" in message:
                raise InvalidAuthTokenError(message) from exc
            raise

        logger.info(
            "Transcribing audio with model=%s compute_type=%s", cfg.model_name, cfg.compute_type
        )

        return model.transcribe(audio_path, batch_size=cfg.batch_size)

    def _align(self, audio_path: Path, transcription: Dict[str, Any]) -> Dict[str, Any]:
        """Align Whisper segments using whisperx alignment model."""

        try:
            import whisperx  # type: ignore
        except ModuleNotFoundError as exc:  # pragma: no cover - external dependency
            raise PipelineError(
                "The 'whisperx' package is required to run alignments."
            ) from exc

        language = transcription.get("language") or self.model_config.language or "en"
        align_model, metadata = whisperx.load_align_model(
            language_code=language, device=self.model_config.device
        )
        logger.info("Aligning transcription for language=%s", language)
        return whisperx.align(
            transcription["segments"],
            align_model,
            metadata,
            str(audio_path),
            self.model_config.device,
        )

    def _diarize(self, audio_path: Path) -> Optional[List[Dict[str, Any]]]:
        """Run speaker diarization when enabled."""

        if not self.diarization_config.enabled:
            return None

        try:
            import whisperx  # type: ignore
        except ModuleNotFoundError as exc:  # pragma: no cover - external dependency
            raise PipelineError(
                "The 'whisperx' package is required to run diarization."
            ) from exc

        logger.info("Running diarization pipeline")
        diarization_pipeline = whisperx.DiarizationPipeline(
            use_auth_token=self.model_config.hf_token,
            device=self.model_config.device,
            **self.diarization_config.diarize_kwargs,
        )
        diarize_segments = diarization_pipeline(str(audio_path))
        return diarize_segments.get("segments") if diarize_segments else None

    def _assign_speakers(
        self, segments: Iterable[Dict[str, Any]], diarization: Optional[List[Dict[str, Any]]]
    ) -> List[Dict[str, Any]]:
        """Merge diarization results back onto aligned segments."""

        try:
            import whisperx  # type: ignore
        except ModuleNotFoundError as exc:  # pragma: no cover - external dependency
            raise PipelineError(
                "The 'whisperx' package is required to assign speakers."
            ) from exc

        segments_list = list(segments)
        if diarization:
            logger.info("Assigning speaker labels to segments")
            segments_list = whisperx.assign_word_speakers(
                diarization, segments_list
            )  # type: ignore[assignment]
        else:
            for segment in segments_list:
                segment.setdefault("speaker", "Speaker 1")
        return segments_list

    def _persist_results(
        self,
        segments: List[Dict[str, Any]],
        alignments: Dict[str, Any],
        audio_path: Path,
    ) -> Dict[str, Path]:
        """Persist transcription outputs to the storage directory."""

        run_dir = self._create_run_directory()
        json_path = run_dir / "transcription.json"
        srt_path = run_dir / "transcription.srt"
        vtt_path = run_dir / "transcription.vtt"

        logger.info("Saving transcription artefacts to %s", run_dir)

        with json_path.open("w", encoding="utf-8") as fh:
            json.dump({"segments": segments, **alignments}, fh, ensure_ascii=False, indent=2)

        self._write_srt(segments, srt_path)
        self._write_vtt(segments, vtt_path)

        # Copy prepared audio for reference (optional but useful for debugging)
        prepared_copy = run_dir / audio_path.name
        if audio_path.exists():
            shutil.copy2(audio_path, prepared_copy)

        return {"json": json_path, "srt": srt_path, "vtt": vtt_path, "audio": prepared_copy}

    def _write_srt(self, segments: Iterable[Dict[str, Any]], destination: Path) -> None:
        """Write SRT file from the provided segments."""

        with destination.open("w", encoding="utf-8") as fh:
            for idx, segment in enumerate(segments, start=1):
                start = self._format_timestamp(segment.get("start", 0.0), srt=True)
                end = self._format_timestamp(segment.get("end", 0.0), srt=True)
                speaker = segment.get("speaker", "Speaker 1")
                text = segment.get("text", "").strip()
                fh.write(f"{idx}\n{start} --> {end}\n[{speaker}] {text}\n\n")

    def _write_vtt(self, segments: Iterable[Dict[str, Any]], destination: Path) -> None:
        """Write WebVTT file from the provided segments."""

        with destination.open("w", encoding="utf-8") as fh:
            fh.write("WEBVTT\n\n")
            for segment in segments:
                start = self._format_timestamp(segment.get("start", 0.0), srt=False)
                end = self._format_timestamp(segment.get("end", 0.0), srt=False)
                speaker = segment.get("speaker", "Speaker 1")
                text = segment.get("text", "").strip()
                fh.write(f"{start} --> {end}\n[{speaker}] {text}\n\n")

    def _create_run_directory(self) -> Path:
        """Create a unique directory within the storage folder for this run."""

        self.storage_dir.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix="transcription_", dir=self.storage_dir))

    def _cleanup(self, paths: Iterable[Path]) -> None:
        """Remove temporary artefacts produced during processing."""

        for path in paths:
            with contextlib.suppress(Exception):
                if path.is_file():
                    path.unlink()
                elif path.is_dir():
                    shutil.rmtree(path)

    # ------------------------------------------------------------------
    # Helper utilities
    # ------------------------------------------------------------------
    @contextlib.contextmanager
    def _temporary_workspace(self) -> Iterable[Path]:
        """Yield a temporary directory that is cleaned up afterwards."""

        workspace = Path(tempfile.mkdtemp(prefix="pipeline_workspace_"))
        try:
            yield workspace
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    @staticmethod
    def _format_timestamp(seconds: float, *, srt: bool) -> str:
        """Format timestamps for subtitle output."""

        milliseconds = int(round(seconds * 1000))
        hours, remainder = divmod(milliseconds, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        secs, millis = divmod(remainder, 1000)
        if srt:
            return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"
        return f"{hours:02}:{minutes:02}:{secs:02}.{millis:03}"


__all__ = [
    "TranscriptionPipeline",
    "ModelConfig",
    "DiarizationConfig",
    "LocalFile",
    "YouTubeSource",
    "PipelineError",
    "InsufficientMemoryError",
    "InvalidAuthTokenError",
]
