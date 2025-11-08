"""Transcription pipeline integration module."""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional, Union


class TranscriptionPipeline:
    """A placeholder transcription pipeline.

    In a production system this would wrap the actual Whisper pipeline or any
    other speech-to-text implementation.  The current implementation keeps the
    surface compatible with such a pipeline and simulates progress updates.
    """

    def __init__(self, hf_token: Optional[str] = None) -> None:
        self.hf_token = hf_token

    def transcribe(
        self,
        source: Union[str, Path],
        destination: Path,
        *,
        progress_callback: Optional[Callable[[float], None]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> Path:
        """Simulate the transcription of ``source`` into ``destination``.

        Parameters
        ----------
        source:
            A path or URL pointing to the media that should be transcribed.
        destination:
            Where to store the generated transcript.  The parent directory must
            exist prior to calling this method.
        progress_callback:
            Callable notified with a value in ``[0.0, 1.0]`` describing the
            progress.  Optional.
        log_callback:
            Callable notified with human readable status updates.  Optional.
        """

        source_path = Path(source)
        if log_callback:
            log_callback(f"Starting transcription of {source_path.name}...")

        if progress_callback:
            progress_callback(0.2)

        # In a real implementation the audio would be processed here.  To keep
        # the code deterministic we simply generate a pseudo transcript that
        # references the input file.
        simulated_transcript = (
            f"Transcription complete for {source_path.name}.\n"
            "This is a simulated transcript produced by the placeholder "
            "TranscriptionPipeline."
        )
        destination.write_text(simulated_transcript, encoding="utf-8")

        if progress_callback:
            progress_callback(1.0)

        if log_callback:
            log_callback("Transcription finished.")

        return destination
