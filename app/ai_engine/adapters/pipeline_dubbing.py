"""Dubbing engine that composes the other engines:

extract audio -> transcribe -> translate -> synthesize (cloned voice) -> fit timing -> mux/export.

Known limitations (reported in every result, not hidden):
  * No lip synchronisation. Timing is fitted per segment by speeding clips up (max
    configurable) and delaying later clips so they never overlap.
  * One voice for all speakers; no speaker diarisation.
  * Original background audio/music is dropped (no source separation) unless
    ``original_audio_volume`` > 0, which mixes the *whole* original track under the dub.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

from app.ai_engine.base import (
    AudioProcessingEngine,
    BaseEngine,
    DubbingEngine,
    DubRequest,
    DubResult,
    EngineStatus,
    ProgressFn,
    SpeechToTextEngine,
    TextToSpeechEngine,
    TimelineItem,
    TranslationEngine,
    noop_progress,
)
from app.ai_engine.dubbing_sync import plan_sync
from app.ai_engine.tts_runner import synthesize_text
from app.core.errors import AudioInvalid, AudioTooLong, ValidationFailed

LIMITATIONS = [
    "No lip synchronisation: timing is fitted per segment by tempo adjustment and delays only.",
    "A single voice is used for every speaker in the source; speaker diarisation is not supported.",
    "Original background music/effects are removed (no source separation) unless original_audio_volume > 0, "
    "which mixes the entire original track, including the original speech, under the dub.",
    "Translation quality depends on the installed translation model and may be imperfect.",
]


class PipelineDubbingEngine(DubbingEngine):
    adapter_name = "pipeline"

    def __init__(self, provider: Callable[[str], BaseEngine]) -> None:
        self._get = provider

    _PARTS = ("audio_processing", "speech_to_text", "translation", "text_to_speech")

    def status(self) -> EngineStatus:
        problems = []
        for kind in self._PARTS:
            st = self._get(kind).status()
            if not st.available:
                problems.append(f"{kind}: {st.reason}")
        if problems:
            return EngineStatus(
                available=False,
                adapter=self.adapter_name,
                reason="Required engines unavailable - " + " | ".join(problems),
                hint="Check GET /api/v1/engines for each engine's setup hint.",
            )
        return EngineStatus(available=True, adapter=self.adapter_name)

    def dub(self, request: DubRequest, progress: ProgressFn = noop_progress) -> DubResult:
        audio: AudioProcessingEngine = self._get("audio_processing")  # type: ignore[assignment]
        stt: SpeechToTextEngine = self._get("speech_to_text")  # type: ignore[assignment]
        translator: TranslationEngine = self._get("translation")  # type: ignore[assignment]
        tts: TextToSpeechEngine = self._get("text_to_speech")  # type: ignore[assignment]
        wd = request.workdir
        wd.mkdir(parents=True, exist_ok=True)
        warnings: list[str] = []

        info = audio.probe(request.input_path)
        if not info.has_audio:
            raise AudioInvalid("The input has no audio track to dub.")
        if info.duration_seconds > request.max_seconds:
            raise AudioTooLong(
                f"Input is {info.duration_seconds:.0f}s; the dubbing limit is {request.max_seconds:.0f}s.",
                details={"max_seconds": request.max_seconds},
            )
        if request.output_format == "mp4" and not info.has_video:
            raise ValidationFailed("output_format 'mp4' requires a video input.")

        # 1. extract
        progress(2, "Extracting audio")
        source_wav = wd / "source_16k.wav"
        audio.to_wav(request.input_path, source_wav, sample_rate=16000)

        # 2. transcribe
        progress(5, "Transcribing")
        transcript = stt.transcribe(
            source_wav, request.source_language, progress=lambda f: progress(5 + 30 * f, "Transcribing")
        )
        segments = [s for s in transcript.segments if s.text.strip()]
        if not segments:
            raise ValidationFailed("No speech was detected in the input.", details={"reason": "NO_SPEECH_DETECTED"})
        source_lang = request.source_language or transcript.language
        if (
            request.source_language is None
            and transcript.language_probability is not None
            and transcript.language_probability < 0.6
        ):
            warnings.append(
                f"Source language detection was uncertain ({transcript.language_probability:.0%}); "
                "set source_language explicitly for better results."
            )

        # 3. translate
        progress(36, "Translating")
        source_texts = [s.text.strip() for s in segments]
        if source_lang.split("-")[0] == request.target_language.split("-")[0]:
            warnings.append("Source and target languages are the same; text was not translated (voice swap only).")
            translated = source_texts
        else:
            translated = translator.translate(source_texts, source_lang, request.target_language)

        # 4. synthesize every segment with the selected voice
        clips: list[Path] = []
        durations: list[float] = []
        sample_rate = 0
        n = len(segments)
        for i, text in enumerate(translated):
            clip = wd / f"seg_{i:05d}.wav"
            lo = 40 + 45 * i / n
            hi = 40 + 45 * (i + 1) / n
            res = synthesize_text(
                tts,
                text=text,
                language=request.target_language,
                reference_wav=request.reference_wav,
                profile_path=request.profile_path,
                speed=1.0,
                out_wav=clip,
                workdir=wd,
                progress=progress,
                progress_range=(lo, hi),
                stage=f"Synthesizing speech ({i + 1}/{n})",
            )
            if sample_rate == 0:
                sample_rate = res.sample_rate
            elif res.sample_rate != sample_rate:
                tmp = wd / f"seg_{i:05d}_rs.wav"
                audio.to_wav(clip, tmp, sample_rate=sample_rate)
                shutil.move(str(tmp), str(clip))
            clips.append(clip)
            durations.append(res.duration_seconds)

        # 5. fit timing
        progress(86, "Fitting timing")
        slots = [(s.start, s.end) for s in segments]
        plan, summary = plan_sync(slots, durations, max_speedup=request.max_speedup)
        timeline: list[TimelineItem] = []
        for item, clip in zip(plan, clips, strict=True):
            path = clip
            if item.tempo > 1.0:
                fast = clip.with_name(clip.stem + "_fast.wav")
                audio.change_tempo(clip, fast, item.tempo)
                path = fast
            timeline.append(TimelineItem(path, item.placed_start))
        if summary["overflowing_segments"]:
            warnings.append(
                f"{summary['overflowing_segments']} segment(s) were longer than their time slot even at the maximum "
                "speed-up and were shifted later; the dub may drift from the picture there."
            )
        if summary["delayed_segments"]:
            warnings.append(
                f"{summary['delayed_segments']} segment(s) start later than the original (max "
                f"{summary['max_delay_seconds']}s late)."
            )

        background = None
        gain = max(0.0, min(1.0, request.original_audio_volume))
        if gain > 0:
            background = wd / "background.wav"
            audio.to_wav(request.input_path, background, sample_rate=sample_rate)
        mixed = wd / "dub_timeline.wav"
        final_seconds = audio.assemble_timeline(
            timeline,
            mixed,
            sample_rate=sample_rate,
            total_seconds=info.duration_seconds,
            background_wav=background,
            background_gain=gain,
        )

        # 6. export
        progress(92, "Exporting")
        out = wd / f"dubbed.{request.output_format}"
        if request.output_format == "mp4":
            audio.mux(request.input_path, mixed, out)
        else:
            audio.encode(mixed, out, request.output_format)
        progress(99, "Finalizing")

        return DubResult(
            output_path=out,
            detected_language=source_lang,
            duration_seconds=final_seconds,
            source_segments=[
                {"id": i, "start": round(s.start, 3), "end": round(s.end, 3), "text": s.text.strip()}
                for i, s in enumerate(segments)
            ],
            translated_segments=[
                {
                    "id": i,
                    "start": round(it.placed_start, 3),
                    "end": round(it.placed_start + it.final_seconds, 3),
                    "text": translated[i],
                    "source_text": source_texts[i],
                    "tempo": it.tempo,
                }
                for i, it in enumerate(plan)
            ],
            sync=summary,
            warnings=warnings,
            limitations=list(LIMITATIONS),
        )
