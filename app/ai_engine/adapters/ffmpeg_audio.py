"""FFmpeg-backed AudioProcessingEngine (no ML involved)."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from app.core.config import Settings
from app.core.errors import AIEngineNotConfigured, MediaProcessingError
from app.ai_engine.base import AudioProcessingEngine, EngineStatus, MediaInfo, TimelineItem
from app.utils.audio import read_wav_mono, write_wav_mono

log = logging.getLogger("voxora.ffmpeg")

_ENCODERS = {
    "wav": ["-c:a", "pcm_s16le"],
    "mp3": ["-c:a", "libmp3lame", "-q:a", "2"],
    "flac": ["-c:a", "flac"],
    "ogg": ["-c:a", "libvorbis", "-q:a", "5"],
    "m4a": ["-c:a", "aac", "-b:a", "192k"],
}


class FFmpegAudioEngine(AudioProcessingEngine):
    adapter_name = "ffmpeg"

    def __init__(self, settings: Settings) -> None:
        self._ffmpeg = settings.ffmpeg_path
        self._ffprobe = settings.ffprobe_path

    # -------------------------------------------------------------- status
    def status(self) -> EngineStatus:
        missing = [b for b in (self._ffmpeg, self._ffprobe) if shutil.which(b) is None]
        if missing:
            return EngineStatus(
                available=False,
                adapter=self.adapter_name,
                reason=f"FFmpeg binaries not found on PATH: {', '.join(missing)}",
                hint="Install FFmpeg (e.g. `apt install ffmpeg`) or set VOXORA_FFMPEG_PATH / VOXORA_FFPROBE_PATH.",
            )
        return EngineStatus(available=True, adapter=self.adapter_name, device="cpu")

    # ------------------------------------------------------------ plumbing
    def _run(self, binary: str, args: list[str], timeout: int = 3600) -> subprocess.CompletedProcess[str]:
        cmd = [binary, *args]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        except FileNotFoundError as exc:
            raise AIEngineNotConfigured("audio_processing", f"'{binary}' was not found") from exc
        except subprocess.TimeoutExpired as exc:
            raise MediaProcessingError("Media processing timed out.") from exc
        if proc.returncode != 0:
            # Full stderr stays in the server log; it may contain internal paths.
            log.error("%s failed (%s): %s", Path(binary).name, proc.returncode, proc.stderr[-2000:])
            raise MediaProcessingError("Media processing failed. The file may be corrupt or unsupported.")
        return proc

    def _ff(self, args: list[str]) -> None:
        self._run(self._ffmpeg, ["-nostdin", "-hide_banner", "-loglevel", "error", "-y", *args])

    # --------------------------------------------------------------- probe
    def probe(self, path: Path) -> MediaInfo:
        proc = self._run(
            self._ffprobe,
            ["-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
            timeout=120,
        )
        try:
            data = json.loads(proc.stdout or "{}")
        except json.JSONDecodeError as exc:
            raise MediaProcessingError("Could not read media information.") from exc
        streams = data.get("streams", [])
        audio = [s for s in streams if s.get("codec_type") == "audio"]
        # Cover art in mp3/m4a appears as a "video" stream; it is not video.
        video = [
            s
            for s in streams
            if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")
        ]
        fmt = data.get("format", {})
        duration = 0.0
        try:
            duration = float(fmt.get("duration") or 0.0)
        except (TypeError, ValueError):
            duration = 0.0
        if duration <= 0:
            for s in streams:
                try:
                    duration = max(duration, float(s.get("duration") or 0.0))
                except (TypeError, ValueError):
                    continue
        a0 = audio[0] if audio else {}
        return MediaInfo(
            duration_seconds=duration,
            has_audio=bool(audio),
            has_video=bool(video),
            audio_codec=a0.get("codec_name"),
            video_codec=video[0].get("codec_name") if video else None,
            sample_rate=int(a0["sample_rate"]) if a0.get("sample_rate") else None,
            channels=int(a0["channels"]) if a0.get("channels") else None,
            format_name=fmt.get("format_name"),
        )

    # ----------------------------------------------------------- conversion
    def to_wav(self, src: Path, dst: Path, *, sample_rate: int = 16000, channels: int = 1) -> None:
        self._ff(
            [
                "-i", str(src),
                "-map", "0:a:0",
                "-vn",
                "-ac", str(channels),
                "-ar", str(sample_rate),
                "-c:a", "pcm_s16le",
                "-f", "wav",
                str(dst),
            ]
        )

    def prepare_voice_reference(self, src_wav: Path, dst_wav: Path, *, sample_rate: int, max_seconds: float) -> None:
        trim = "silenceremove=start_periods=1:start_duration=0.05:start_threshold=-50dB"
        chain = f"highpass=f=70,{trim},areverse,{trim},areverse,loudnorm=I=-20:TP=-2:LRA=7"
        self._ff(
            [
                "-i", str(src_wav),
                "-af", chain,
                "-t", f"{max_seconds:.2f}",
                "-ac", "1",
                "-ar", str(sample_rate),
                "-c:a", "pcm_s16le",
                "-f", "wav",
                str(dst_wav),
            ]
        )

    def encode(self, src_wav: Path, dst: Path, fmt: str) -> None:
        if fmt not in _ENCODERS:
            raise MediaProcessingError(f"Unsupported output format: {fmt}")
        fmt_flag = ["-f", {"m4a": "ipod", "ogg": "ogg"}.get(fmt, fmt)]
        self._ff(["-i", str(src_wav), "-vn", *_ENCODERS[fmt], *fmt_flag, str(dst)])

    def change_tempo(self, src_wav: Path, dst_wav: Path, factor: float) -> None:
        factor = float(factor)
        if factor <= 0:
            raise MediaProcessingError("Invalid tempo factor.")
        filters: list[str] = []
        f = factor
        while f > 2.0:
            filters.append("atempo=2.0")
            f /= 2.0
        while f < 0.5:
            filters.append("atempo=0.5")
            f /= 0.5
        filters.append(f"atempo={f:.5f}")
        self._ff(["-i", str(src_wav), "-af", ",".join(filters), "-c:a", "pcm_s16le", "-f", "wav", str(dst_wav)])

    # ------------------------------------------------------------- timeline
    def assemble_timeline(
        self,
        items: Sequence[TimelineItem],
        dst_wav: Path,
        *,
        sample_rate: int,
        total_seconds: float,
        background_wav: Path | None = None,
        background_gain: float = 0.0,
    ) -> float:
        end_needed = max([total_seconds] + [0.0])
        clips: list[tuple[int, np.ndarray]] = []
        for it in items:
            samples, sr = read_wav_mono(it.wav_path)
            if sr != sample_rate:
                raise MediaProcessingError("Timeline clips must share the timeline sample rate.")
            offset = int(round(it.start_seconds * sample_rate))
            clips.append((offset, samples))
            end_needed = max(end_needed, (offset + len(samples)) / sample_rate)

        total = int(np.ceil(end_needed * sample_rate)) + 1
        buf = np.zeros(total, dtype=np.float32)
        if background_wav is not None and background_gain > 0:
            bg, bsr = read_wav_mono(background_wav)
            if bsr != sample_rate:
                raise MediaProcessingError("Background audio must share the timeline sample rate.")
            n = min(len(bg), total)
            buf[:n] += bg[:n] * float(background_gain)
        for offset, samples in clips:
            n = min(len(samples), total - offset)
            if n > 0:
                buf[offset : offset + n] += samples[:n]
        peak = float(np.max(np.abs(buf))) if total else 0.0
        if peak > 0.98:  # avoid hard clipping when overlapping with background
            buf *= 0.98 / peak
        write_wav_mono(dst_wav, buf, sample_rate)
        return total / sample_rate

    # ------------------------------------------------------------------ mux
    def mux(self, video: Path, audio_wav: Path, dst: Path) -> None:
        base = ["-i", str(video), "-i", str(audio_wav), "-map", "0:v:0", "-map", "1:a:0"]
        tail = ["-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(dst)]
        try:
            self._ff([*base, "-c:v", "copy", *tail])
        except MediaProcessingError:
            log.info("Stream copy into container failed; re-encoding video with libx264")
            self._ff(
                [*base, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", *tail]
            )
