"""
Transcription Service.

Supports two transcription providers:
- `openai`: OpenAI or any OpenAI-compatible audio transcription API
- `faster-whisper`: local faster-whisper inference

The app keeps the same session and file-upload flow regardless of provider.
"""

import io
import json
import logging
import time
import wave
import base64
import difflib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx
import numpy as np

from config import config

logger = logging.getLogger(__name__)
_GLOSSARY_CACHE: dict[str, object] = {"path": None, "mtime": None, "entries": []}
LOCAL_RECORDING_ENGINE = "faster-whisper"

try:
    from faster_whisper import WhisperModel

    FASTER_WHISPER_AVAILABLE = True
except ImportError:
    FASTER_WHISPER_AVAILABLE = False
    logger.warning("faster-whisper not installed. Run: pip install faster-whisper")

try:
    from pydub import AudioSegment

    PYDUB_AVAILABLE = True
except ImportError:
    AudioSegment = None
    PYDUB_AVAILABLE = False
    logger.warning("pydub not installed. Uploaded-file transcription needs: pip install pydub")

try:
    from pydub.utils import which as pydub_which
except ImportError:
    pydub_which = None


@dataclass
class TranscriptSegment:
    """Represents a single transcribed segment of speech."""

    text: str
    start_time: float
    end_time: float
    confidence: float = 0.0
    language: str = "en"
    speaker: str = ""
    is_unclear: bool = False

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "confidence": self.confidence,
            "language": self.language,
            "speaker": self.speaker,
            "is_unclear": self.is_unclear,
        }


HALLUCINATION_PHRASES = frozenset(
    [
        # YouTube/video outro hallucinations
        "thank you for watching",
        "thanks for watching",
        "subscribe to",
        "like and subscribe",
        "please subscribe",
        "thank you for listening",
        "thanks for listening",
        "see you next time",
        "see you in the next video",
        "see you in the next one",
        "don't forget to subscribe",
        "hit the bell icon",
        "leave a comment",
        "share this video",
        # Common Whisper hallucination phrases
        "bye bye",
        "bye-bye",
        "music",
        "♪",
        "...",
        "you",
        "i",
        "oh",
        "so",
        "okay",
        "yeah",
        "yes",
        "no",
        "the end",
        "thank you",
        "thanks",
        "applause",
        "laughter",
        "silence",
        "foreign",
        "subtitles by",
        "translated by",
        "amara.org",
        # Whisper noise-fill hallucinations
        "ugh",
        "hmm",
        "huh",
        "mhm",
        "ah",
        "um",
        "uh",
        "er",
        "hm",
        # Sound descriptions that Whisper produces on noise
        "beep",
        "ring",
        "ding",
        "buzz",
        "click",
        "pop",
        "static",
        "noise",
        "breathing",
        "coughing",
        "sniffing",
        "shuffling",
        "clapping",
        "typing",
        "tapping",
        # Chinese/Korean/Japanese artifacts from Bluetooth codec noise
        "字幕",
        "請",
        "谢谢",
        "ご視聴",
        "시청",
        # Subtitle service tags
        "transcribed by",
        "captioned by",
        "provided by",
    ]
)

# Regex patterns that catch repetitive hallucination (e.g. "I'm going to I'm going to I'm going to")
_REPETITION_RE = re.compile(
    r"^(.{2,30})\s*(?:\1\s*){2,}$",
    re.IGNORECASE | re.DOTALL,
)

TRANSCRIPT_POLISH_SYSTEM_PROMPT = """You are cleaning a raw meeting transcript for readability.

CRITICAL RULES:
1. Preserve the meaning and factual content exactly.
2. Do not summarize, shorten, omit, or add information.
3. Preserve names, numbers, dates, tasks, product names, and technical terms exactly when present.
4. Remove only obvious filler repetition and formatting noise.
5. Split the transcript into readable transcript segments of 1-3 sentences each.
6. Do not invent speaker labels.
7. If the transcript already contains English phrasing, keep that wording instead of paraphrasing it.
8. If a short non-English phrase appears inside an otherwise English meeting transcript, translate it into natural English without dropping any meaning.
9. Return ONLY valid JSON in this format:
{
  "segments": ["segment 1", "segment 2"]
}
"""

FILE_SEGMENT_REVIEW_SYSTEM_PROMPT = """You are reviewing one uploaded-audio transcript segment.

Rules:
1. Convert the segment into clear natural English when needed.
2. Preserve the meaning, names, numbers, and technical terms exactly.
2a. If a glossary is provided, prefer the glossary spellings exactly.
3. Do not summarize or shorten.
4. If the segment is obviously hallucinated, random filler, music/noise text, or too broken to trust, mark it for drop.
5. If the segment is partly understandable but still risky, keep the best English text and mark it as review-needed.
6. Return ONLY valid JSON:
{
  "text": "clean English text",
  "drop": false,
  "review": false
}
If it should be discarded:
{
  "text": "",
  "drop": true,
  "review": true
}
"""

LIVE_CHUNK_GUARDRAIL = (
    "CRITICAL: If this audio contains silence, background noise, music, hum, "
    "Bluetooth codec artifacts, video playback, system sounds, keyboard typing, "
    "breathing, or any audio without clear human speech, return an EMPTY transcript. "
    "Do NOT guess words. Do NOT invent dialogue. Do NOT output filler phrases like "
    "'thank you', 'bye bye', 'subscribe', or any common Whisper hallucination. "
    "Only transcribe clearly audible human speech. When in doubt, output nothing."
)

LIVE_TRANSLATION_SYSTEM_PROMPT = """You are cleaning one short live meeting transcript segment.

Rules:
1. Convert the segment into clear natural English.
2. Preserve the original meaning exactly.
2a. If a glossary is provided, prefer the glossary spellings exactly.
3. If the segment is already good English, keep it concise and natural.
4. If the segment is gibberish, contradictory, random words, obvious hallucination, or too unclear to trust, drop it.
5. Do not add information, explanation, punctuation-only filler, or speaker names.
6. Return ONLY valid JSON:
{
  "text": "clean English text",
  "drop": false
}
If the segment should be discarded, return:
{
  "text": "",
  "drop": true
}
"""


def _load_transcription_glossary() -> list[dict[str, list[str] | str]]:
    """Load preferred names and technical terms from the glossary file."""

    glossary_path = config.get_transcription_glossary_path()
    if not glossary_path.exists():
        return []

    try:
        stat = glossary_path.stat()
    except OSError:
        return []

    cached_path = _GLOSSARY_CACHE.get("path")
    cached_mtime = _GLOSSARY_CACHE.get("mtime")
    if cached_path == str(glossary_path) and cached_mtime == stat.st_mtime:
        return list(_GLOSSARY_CACHE.get("entries", []))

    entries: list[dict[str, list[str] | str]] = []

    try:
        for raw_line in glossary_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            if "|" in line:
                canonical, alias_blob = [part.strip() for part in line.split("|", 1)]
                aliases = [alias.strip() for alias in alias_blob.split(",") if alias.strip()]
            else:
                canonical = line
                aliases = []

            if not canonical:
                continue

            deduped_aliases: list[str] = []
            seen = {canonical.lower()}
            for alias in aliases:
                lowered = alias.lower()
                if lowered in seen:
                    continue
                seen.add(lowered)
                deduped_aliases.append(alias)

            entries.append({"canonical": canonical, "aliases": deduped_aliases})
    except OSError as exc:
        logger.warning("Could not read transcription glossary: %s", exc)
        return []

    _GLOSSARY_CACHE["path"] = str(glossary_path)
    _GLOSSARY_CACHE["mtime"] = stat.st_mtime
    _GLOSSARY_CACHE["entries"] = entries
    return list(entries)


def _build_glossary_prompt_block() -> str:
    """Format the glossary as a short prompt hint for speech/text cleanup."""

    entries = _load_transcription_glossary()
    if not entries:
        return ""

    lines = ["Preferred spellings and project terms. Use these exact forms when they are spoken:"]
    for entry in entries[:40]:
        canonical = str(entry["canonical"])
        aliases = list(entry["aliases"])
        if aliases:
            lines.append(f"- {canonical} (possible variants: {', '.join(aliases[:4])})")
        else:
            lines.append(f"- {canonical}")

    return "\n".join(lines)


def _alias_pattern(alias: str) -> str:
    """Create a tolerant regex for an alias phrase."""

    alias = alias.strip()
    if not alias:
        return ""

    pieces: list[str] = []
    for char in alias:
        if char.isalnum():
            pieces.append(re.escape(char))
        elif char.isspace() or char in {"-", "_", "/", "."}:
            pieces.append(r"[\s\-_/\.]*")
        else:
            pieces.append(re.escape(char))
    return "".join(pieces)


def _apply_glossary_corrections(text: str) -> str:
    """Replace known alias spellings with canonical glossary terms."""

    corrected = str(text or "").strip()
    if not corrected:
        return corrected

    for entry in _load_transcription_glossary():
        canonical = str(entry["canonical"])
        aliases = [canonical, *list(entry["aliases"])]
        # Longest aliases first so multi-word variants win.
        for alias in sorted(aliases, key=len, reverse=True):
            pattern_body = _alias_pattern(alias)
            if not pattern_body:
                continue
            pattern = re.compile(rf"(?<!\w){pattern_body}(?!\w)", re.IGNORECASE)
            corrected = pattern.sub(canonical, corrected)

    return re.sub(r"\s+", " ", corrected).strip()


def _get_transcription_provider_status(engine: str) -> dict:
    """Return health information for a specific transcription provider."""

    if engine == "openai":
        key_present = bool(config.OPENAI_API_KEY)
        provider_name = "OpenAI-compatible API"
        if "openrouter.ai" in config.OPENAI_BASE_URL:
            provider_name = "OpenRouter"

        return {
            "engine": "openai",
            "provider": provider_name,
            "reachable": key_present,
            "model_available": key_present,
            "ready": key_present,
            "model": config.OPENAI_TRANSCRIPTION_MODEL,
            "detail": (
                f"{provider_name} transcription ready: {config.OPENAI_TRANSCRIPTION_MODEL}"
                if key_present
                else "Cloud transcription is disabled. Add OPENAI_API_KEY to enable OpenAI-compatible speech-to-text."
            ),
        }

    if engine == "faster-whisper":
        return {
            "engine": "faster-whisper",
            "provider": "faster-whisper",
            "reachable": FASTER_WHISPER_AVAILABLE,
            "model_available": FASTER_WHISPER_AVAILABLE,
            "ready": FASTER_WHISPER_AVAILABLE,
            "model": config.WHISPER_MODEL_SIZE,
            "detail": (
                f"Local transcription ready: faster-whisper {config.WHISPER_MODEL_SIZE}"
                if FASTER_WHISPER_AVAILABLE
                else "Local transcription is disabled. Install faster-whisper to use the local engine."
            ),
        }

    return {
        "engine": engine,
        "provider": engine or "unknown",
        "reachable": False,
        "model_available": False,
        "ready": False,
        "model": "",
        "detail": f"Unsupported TRANSCRIBE_ENGINE `{config.TRANSCRIPTION_ENGINE}`.",
    }


def get_transcription_provider_status() -> dict:
    """Return health information for the configured transcription provider."""

    return _get_transcription_provider_status(config.TRANSCRIPTION_ENGINE.lower())


def get_local_recording_provider_status() -> dict:
    """Return health information for the built-in local recording engine."""

    return _get_transcription_provider_status(LOCAL_RECORDING_ENGINE)


def _is_hallucination_text(text: str) -> bool:
    """Detect obvious junk phrases that should be dropped."""

    text_lower = text.lower().strip().rstrip(".,!?")
    if not text_lower:
        return True

    if text_lower in HALLUCINATION_PHRASES:
        return True

    words = text_lower.split()

    # Single-character or empty output
    if len(text_lower.replace(" ", "")) <= 1:
        return True

    # All words are the same (e.g. "the the the the")
    if len(words) > 2 and len(set(words)) == 1:
        return True

    # Two unique words but 4+ total words (e.g. "thank you thank you thank you")
    if len(words) >= 4 and len(set(words)) <= 2:
        return True

    # First half equals second half (e.g. "hello world hello world")
    if len(words) >= 6:
        mid = len(words) // 2
        if words[:mid] == words[mid : 2 * mid]:
            return True

    # Regex repetition detection (catches "I'm going to I'm going to I'm going to")
    if _REPETITION_RE.match(text_lower):
        return True

    # Mostly non-ASCII characters (Bluetooth codec artifacts producing Chinese/Korean/etc)
    # CRITICAL: We must ignore Tamil Unicode characters (U+0B80 to U+0BFF) so real Tamil is not blocked!
    tamil_chars = sum(1 for c in text_lower if '\u0b80' <= c <= '\u0bff')
    other_non_ascii = sum(1 for c in text_lower if ord(c) > 127) - tamil_chars
    
    if text_lower and (other_non_ascii / len(text_lower)) > 0.4:
        return True

    # Very short text that is just punctuation or symbols (exempting Tamil characters)
    stripped_alpha = re.sub(r'[^a-zA-Z\u0b80-\u0bff]', '', text_lower)
    if len(stripped_alpha) < 2:
        return True

    return False


def _split_transcript_into_readable_chunks(text: str) -> list[str]:
    """Split long transcript text into readable sentence groups."""

    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return []

    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    chunks: list[str] = []
    current = ""

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        candidate = f"{current} {sentence}".strip() if current else sentence
        if current and (len(candidate) > 280 or candidate.count(". ") >= 4):
            chunks.append(current)
            current = sentence
        else:
            current = candidate

    if current:
        chunks.append(current)

    if not chunks and cleaned:
        chunks = [cleaned]

    return chunks


def _normalized_overlap_tokens(text: str) -> list[str]:
    """Normalize text into comparison-friendly tokens for overlap detection."""

    normalized = re.sub(r"[^\w\s]", " ", str(text or "").lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized.split()


def _merge_transcript_text(existing: str, incoming: str) -> str:
    """Merge overlapping transcript windows without dropping new content."""

    existing = re.sub(r"\s+", " ", str(existing or "")).strip()
    incoming = re.sub(r"\s+", " ", str(incoming or "")).strip()

    if not existing:
        return incoming
    if not incoming:
        return existing

    existing_tokens = existing.split()
    incoming_tokens = incoming.split()
    existing_norm = _normalized_overlap_tokens(existing)
    incoming_norm = _normalized_overlap_tokens(incoming)

    # Skip near-total duplicates from overlapped windows.
    if incoming_norm and len(incoming_norm) >= 6:
        existing_tail = existing_norm[-len(incoming_norm) :]
        if existing_tail == incoming_norm:
            return existing

    max_window = min(len(existing_norm), len(incoming_norm), 45)
    overlap_words = 0

    for window in range(max_window, 4, -1):
        if existing_norm[-window:] == incoming_norm[:window]:
            overlap_words = window
            break

    if overlap_words:
        return f"{existing} {' '.join(incoming_tokens[overlap_words:])}".strip()

    # Fuzzy fallback for slightly different punctuation/casing in overlapped edges.
    existing_tail_text = " ".join(existing_norm[-18:])
    incoming_head_text = " ".join(incoming_norm[:18])
    if existing_tail_text and incoming_head_text:
        similarity = difflib.SequenceMatcher(None, existing_tail_text, incoming_head_text).ratio()
        if similarity >= 0.92:
            return f"{existing} {' '.join(incoming_tokens[8:])}".strip()

    return f"{existing} {incoming}".strip()


def _extract_prompt_tail(text: str, max_words: int = 18) -> str:
    """Keep a short trailing context hint for the next upload chunk."""

    words = re.sub(r"\s+", " ", str(text or "")).strip().split()
    if not words:
        return ""
    return " ".join(words[-max_words:])


def _build_file_transcription_prompt(previous_tail: str = "") -> str:
    """Compose a higher-context prompt for uploaded audio windows."""

    parts = [config.OPENAI_TRANSCRIPTION_PROMPT]
    glossary = _build_glossary_prompt_block()
    if glossary:
        parts.append(glossary)
    if previous_tail:
        parts.append(
            "Previous transcript ending for continuity only. "
            "Use it to continue the sentence naturally, but do not repeat earlier lines unless they are spoken again:\n"
            f"{previous_tail}"
        )
    return "\n\n".join(part.strip() for part in parts if part.strip())


def _get_live_signal_stats(audio_data: np.ndarray) -> tuple[float, float]:
    """Return RMS and peak levels for a live audio chunk."""

    if audio_data.size == 0:
        return 0.0, 0.0

    rms = float(np.sqrt(np.mean(audio_data**2)))
    peak = float(np.max(np.abs(audio_data)))
    return rms, peak


def _should_skip_live_chunk(audio_data: np.ndarray) -> bool:
    """Drop low-signal live chunks before they reach the speech model.

    Uses stricter thresholds to prevent near-silent Bluetooth noise,
    video playback hum, and codec artifacts from being transcribed.
    """

    rms, peak = _get_live_signal_stats(audio_data)

    # Primary gate: allow quieter but still speech-like meeting chunks through.
    # Requiring both metrics to be low avoids throwing away softer Zoom voices.
    if rms < config.LIVE_MIN_RMS and peak < config.LIVE_MIN_PEAK:
        return True

    # Secondary gate: if energy is borderline, require sustained signal.
    # This catches Bluetooth codec noise that has occasional spikes but low RMS.
    if rms < config.LIVE_MIN_RMS * 1.5 and peak < config.LIVE_MIN_PEAK * 1.35:
        # Check if at least 10% of samples exceed the dynamic minimum amplitude
        sample_threshold = config.LIVE_MIN_RMS * 0.4
        active_samples = np.sum(np.abs(audio_data) > sample_threshold)
        active_ratio = active_samples / max(audio_data.size, 1)
        if active_ratio < 0.06:
            return True

    return False


def _build_chunk_transcription_prompt() -> str:
    """Compose a chunk/file prompt that discourages guessing on low-signal audio."""

    parts = [LIVE_CHUNK_GUARDRAIL, config.OPENAI_TRANSCRIPTION_PROMPT]
    glossary = _build_glossary_prompt_block()
    if glossary:
        parts.append(glossary)
    return "\n\n".join(part.strip() for part in parts if part.strip())


def _build_live_chunk_transcription_prompt(previous_tail: str = "") -> str:
    """Compose a continuity-aware prompt for overlapped live windows."""

    parts = [_build_chunk_transcription_prompt()]
    if previous_tail:
        parts.append(
            "Recent transcript tail for continuity only. Use it to continue the sentence naturally, "
            "but do not repeat words that were already transcribed in the earlier live chunk:\n"
            f"{previous_tail}"
        )
    return "\n\n".join(part.strip() for part in parts if part.strip())


def _estimate_cloud_confidence(
    text: str,
    audio_data: Optional[np.ndarray] = None,
    duration: float = 0.0,
) -> float:
    """Estimate confidence for provider responses that do not expose token-level confidence.

    Heavily penalizes:
    - Very short text from long audio chunks (strong hallucination signal)
    - High non-ASCII ratio (Bluetooth codec artifact)
    - Low audio energy
    """

    cleaned = str(text or "").strip()
    if not cleaned or _is_hallucination_text(cleaned):
        return 0.0

    words = cleaned.split()
    text_score = 0.55

    # Word count scoring — more words generally means more real speech
    if len(words) >= 6:
        text_score += 0.16
    elif len(words) >= 4:
        text_score += 0.10
    elif len(words) == 1:
        text_score -= 0.20
    elif len(words) <= 2:
        text_score -= 0.10

    # Proper punctuation is a positive signal
    if len(cleaned) >= 18:
        text_score += 0.06
    if cleaned[-1:] in ".!?":
        text_score += 0.04

    # Non-ASCII penalty (Bluetooth noise produces CJK characters, ignore Tamil script)
    tamil_chars = sum(1 for c in cleaned if '\u0b80' <= c <= '\u0bff')
    other_non_ascii = sum(1 for char in cleaned if ord(char) > 127) - tamil_chars
    if cleaned and (other_non_ascii / len(cleaned)) > 0.15:
        text_score -= 0.40

    # Heavy penalty: short output from long audio = almost certainly hallucination
    if duration >= 3.0 and len(words) <= 2:
        text_score -= 0.30
    elif duration >= 5.0 and len(words) <= 4:
        text_score -= 0.20
    elif duration >= 8.0 and len(words) <= 6:
        text_score -= 0.15

    # Words-per-second sanity check: real speech is ~2-4 WPS
    if duration > 0.5:
        wps = len(words) / duration
        if wps > 6.0:  # Suspiciously fast — likely hallucination cramming
            text_score -= 0.15
        elif wps < 0.3:  # Almost no words for the duration
            text_score -= 0.20

    signal_score = 0.55
    if audio_data is not None and audio_data.size:
        rms, peak = _get_live_signal_stats(audio_data)
        signal_score = min(1.0, max((rms / 0.06), (peak / 0.22)))
        signal_score = max(0.05, signal_score)

    confidence = (0.25 * signal_score) + (0.75 * max(0.0, min(text_score, 1.0)))
    return max(0.05, min(confidence, 0.98))


def _numpy_audio_to_wav_bytes(audio_data: np.ndarray) -> bytes:
    """Encode float32 mono audio into a 16-bit PCM WAV payload."""

    clipped = np.clip(audio_data, -1.0, 1.0)
    pcm = (clipped * 32767.0).astype(np.int16)

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(config.CHANNELS)
        wav_file.setsampwidth(config.AUDIO_FORMAT_WIDTH)
        wav_file.setframerate(config.SAMPLE_RATE)
        wav_file.writeframes(pcm.tobytes())

    return buffer.getvalue()


def _audiosegment_to_wav_bytes(segment: AudioSegment) -> bytes:
    """Normalize a file chunk and export it as in-memory WAV."""

    normalized = (
        segment.set_frame_rate(config.SAMPLE_RATE)
        .set_channels(config.CHANNELS)
        .set_sample_width(config.AUDIO_FORMAT_WIDTH)
    )

    buffer = io.BytesIO()
    normalized.export(buffer, format="wav")
    return buffer.getvalue()


def _ffmpeg_stack_available() -> bool:
    """Return True when the local ffmpeg/ffprobe toolchain is available."""

    if not pydub_which:
        return False
    return bool(pydub_which("ffmpeg") and pydub_which("ffprobe"))


def _is_openrouter_base_url() -> bool:
    """Return True when the configured provider is OpenRouter."""

    return "openrouter.ai" in config.OPENAI_BASE_URL


def _guess_audio_format(filename: str) -> str:
    """Infer an audio format string from a filename."""

    suffix = Path(filename).suffix.lower().lstrip(".")
    if suffix == "mp3":
        return "mp3"
    if suffix in {"wav", "wave"}:
        return "wav"
    if suffix in {"m4a", "mp4"}:
        return "mp4"
    if suffix in {"ogg", "oga"}:
        return "ogg"
    if suffix == "flac":
        return "flac"
    if suffix == "webm":
        return "webm"
    return "wav"


class BaseTranscriptionEngine:
    """Shared provider interface for transcription engines."""

    provider_name: str = "unknown"

    def load_model(self):
        raise NotImplementedError

    def transcribe(
        self,
        audio_data: np.ndarray,
        time_offset: float = 0.0,
    ) -> list[TranscriptSegment]:
        raise NotImplementedError

    def transcribe_file(self, file_path: str | Path) -> list[TranscriptSegment]:
        raise NotImplementedError


class LocalTranscriptionEngine(BaseTranscriptionEngine):
    """High-accuracy local transcription using faster-whisper."""

    provider_name = "faster-whisper"

    def __init__(self):
        self._model: Optional[WhisperModel] = None
        self._loaded = False

    def load_model(self):
        """Load the local Whisper model."""

        if not FASTER_WHISPER_AVAILABLE:
            raise RuntimeError(
                "faster-whisper is not installed. Run: pip install faster-whisper"
            )

        if self._loaded:
            return

        model_name = config.WHISPER_MODEL_SIZE
        device = config.WHISPER_DEVICE
        compute = config.WHISPER_COMPUTE_TYPE

        logger.info(
            "Loading Whisper model: %s (device=%s, compute=%s)",
            model_name,
            device,
            compute,
        )
        start = time.time()

        self._model = WhisperModel(
            model_name,
            device=device,
            compute_type=compute,
        )

        elapsed = time.time() - start
        logger.info("Whisper model loaded in %.1fs", elapsed)
        self._loaded = True

    def transcribe(
        self,
        audio_data: np.ndarray,
        time_offset: float = 0.0,
    ) -> list[TranscriptSegment]:
        if not self._loaded:
            self.load_model()

        if _should_skip_live_chunk(audio_data):
            return []

        return self._transcribe_source(audio_data, time_offset=time_offset)

    def transcribe_file(self, file_path: str | Path) -> list[TranscriptSegment]:
        if not self._loaded:
            self.load_model()
        return self._transcribe_source(str(file_path), time_offset=0.0)

    def _transcribe_source(
        self,
        source: np.ndarray | str,
        time_offset: float = 0.0,
    ) -> list[TranscriptSegment]:
        segments_out: list[TranscriptSegment] = []

        try:
            segments, info = self._model.transcribe(
                source,
                language=None,
                task=config.WHISPER_TASK,
                condition_on_previous_text=False,
                no_speech_threshold=config.NO_SPEECH_THRESHOLD,
                log_prob_threshold=-1.0,
                compression_ratio_threshold=2.4,
                word_timestamps=True,
                vad_filter=True,
                vad_parameters=dict(
                    min_silence_duration_ms=500,
                    speech_pad_ms=200,
                ),
                beam_size=5,
                suppress_blank=True,
            )

            detected_language = info.language if info else "en"

            for segment in segments:
                text = _apply_glossary_corrections(segment.text.strip())
                if not text:
                    continue

                no_speech = getattr(segment, "no_speech_prob", 0.0)
                if no_speech > config.NO_SPEECH_THRESHOLD:
                    continue

                avg_logprob = getattr(segment, "avg_logprob", -2.0)
                confidence = max(0.0, min(1.0, 1.0 + avg_logprob / 2.0))

                if self._is_hallucination(text, segment):
                    continue

                is_unclear = confidence < config.CONFIDENCE_THRESHOLD
                if is_unclear:
                    text = "[unclear]"

                segments_out.append(
                    TranscriptSegment(
                        text=text,
                        start_time=time_offset + segment.start,
                        end_time=time_offset + segment.end,
                        confidence=confidence,
                        language=detected_language,
                        is_unclear=is_unclear,
                    )
                )

        except Exception as exc:
            logger.error("Local transcription error: %s", exc)
            return []

        return segments_out

    def _is_hallucination(self, text: str, segment) -> bool:
        if _is_hallucination_text(text):
            return True

        avg_logprob = getattr(segment, "avg_logprob", -2.0)
        no_speech_prob = getattr(segment, "no_speech_prob", 0.0)

        # Very low log probability with short text = hallucination
        if avg_logprob < -1.5 and len(text.lower().strip()) < 5:
            return True

        # Moderate log probability penalty for short text
        if avg_logprob < -1.0 and len(text.split()) <= 2:
            return True

        # High no-speech probability combined with low confidence
        if no_speech_prob > 0.4 and avg_logprob < -0.8:
            return True

        # Compression ratio check: Whisper repeats itself when confused
        compression_ratio = getattr(segment, "compression_ratio", 0.0)
        if compression_ratio > 2.2 and avg_logprob < -0.6:
            return True

        return False


class OpenAITranscriptionEngine(BaseTranscriptionEngine):
    """Speech-to-text via the OpenAI-compatible audio transcription API."""

    provider_name = "openai"

    def __init__(self):
        self._loaded = False
        self._live_prompt_tail = ""

    def load_model(self):
        status = get_transcription_provider_status()
        if not status["ready"]:
            raise RuntimeError(status["detail"])
        self._loaded = True

    def transcribe(
        self,
        audio_data: np.ndarray,
        time_offset: float = 0.0,
    ) -> list[TranscriptSegment]:
        if not self._loaded:
            self.load_model()

        if _should_skip_live_chunk(audio_data):
            return []

        duration = max(len(audio_data) / float(config.SAMPLE_RATE), 0.1)
        text = self._transcribe_bytes(
            _numpy_audio_to_wav_bytes(audio_data),
            filename="live-chunk.wav",
            prompt=_build_live_chunk_transcription_prompt(self._live_prompt_tail),
            timeout_override=min(
                float(config.OPENAI_TIMEOUT_SECONDS),
                max(float(config.LIVE_TRANSCRIPTION_TIMEOUT_SECONDS), duration + 4.0),
            ),
            max_attempts_override=max(1, int(config.LIVE_TRANSCRIPTION_MAX_RETRIES) + 1),
        )
        cleaned_text = _apply_glossary_corrections(re.sub(r"\s+", " ", str(text or "")).strip())
        confidence = _estimate_cloud_confidence(cleaned_text, audio_data=audio_data, duration=duration)
        if cleaned_text and not _is_hallucination_text(cleaned_text):
            if confidence >= max(config.CONFIDENCE_THRESHOLD, 0.58) and len(cleaned_text.split()) >= 3:
                merged_tail = f"{self._live_prompt_tail} {cleaned_text}".strip()
                self._live_prompt_tail = _extract_prompt_tail(merged_tail, max_words=24)
        return self._build_segments_from_text(
            cleaned_text,
            time_offset,
            duration,
            confidence=confidence,
        )

    def transcribe_file(self, file_path: str | Path) -> list[TranscriptSegment]:
        if not self._loaded:
            self.load_model()

        file_path = Path(file_path)

        if PYDUB_AVAILABLE and _ffmpeg_stack_available():
            audio = AudioSegment.from_file(file_path)
            total_duration = max(len(audio) / 1000.0, 0.1)
            merged_text = self._transcribe_file_with_context_windows(audio)
            if merged_text:
                return self._build_segments_from_full_transcript(merged_text, total_duration)

        logger.warning(
            "ffmpeg/ffprobe not available. Falling back to direct provider upload for %s",
            file_path.name,
        )
        return self._transcribe_file_direct(file_path)

    def _transcribe_file_with_context_windows(self, audio: AudioSegment) -> str:
        """Transcribe uploaded audio in larger overlapping windows, then merge them."""

        chunk_ms = max(15000, config.OPENAI_UPLOAD_CHUNK_SECONDS * 1000)
        overlap_ms = max(0, min(config.OPENAI_UPLOAD_CHUNK_OVERLAP_SECONDS * 1000, chunk_ms // 3))
        step_ms = max(5000, chunk_ms - overlap_ms)

        merged_text = ""
        previous_tail = ""

        for chunk_start in range(0, len(audio), step_ms):
            chunk = audio[chunk_start : min(chunk_start + chunk_ms, len(audio))]
            if len(chunk) == 0 or chunk.rms <= 0:
                continue

            prompt = _build_file_transcription_prompt(previous_tail)

            text = self._transcribe_bytes(
                _audiosegment_to_wav_bytes(chunk),
                filename=f"upload-{chunk_start}.wav",
                prompt=prompt,
            )

            cleaned = _apply_glossary_corrections(re.sub(r"\s+", " ", str(text or "")).strip())
            if not cleaned or _is_hallucination_text(cleaned):
                continue

            merged_text = _merge_transcript_text(merged_text, cleaned)
            previous_tail = _extract_prompt_tail(merged_text)

        return merged_text.strip()

    def _transcribe_bytes(
        self,
        audio_bytes: bytes,
        filename: str,
        prompt: Optional[str] = None,
        timeout_override: Optional[float] = None,
        max_attempts_override: Optional[int] = None,
    ) -> str:
        if _is_openrouter_base_url():
            return self._transcribe_bytes_openrouter(
                audio_bytes,
                filename,
                prompt,
                timeout_override=timeout_override,
                max_attempts_override=max_attempts_override,
            )

        endpoint = (
            "audio/translations"
            if config.WHISPER_TASK.lower() == "translate"
            else "audio/transcriptions"
        )
        headers = {"Authorization": f"Bearer {config.OPENAI_API_KEY}"}
        if config.OPENAI_PROJECT:
            headers["OpenAI-Project"] = config.OPENAI_PROJECT

        data = {
            "model": config.OPENAI_TRANSCRIPTION_MODEL,
            "response_format": "json",
            "prompt": prompt or _build_chunk_transcription_prompt(),
        }

        response = self._post_with_retries(
            f"{config.OPENAI_BASE_URL.rstrip('/')}/{endpoint}",
            headers=headers,
            data=data,
            files={"file": (filename, audio_bytes, "audio/wav")},
            timeout_override=timeout_override,
            max_attempts_override=max_attempts_override,
        )

        if response.status_code != 200:
            raise RuntimeError(
                f"Cloud transcription provider returned status {response.status_code}: {response.text}"
            )

        payload = response.json()
        text = payload.get("text", "")
        if not isinstance(text, str):
            text = str(text or "")
        return _apply_glossary_corrections(text.strip())

    def _transcribe_bytes_openrouter(
        self,
        audio_bytes: bytes,
        filename: str,
        prompt: Optional[str] = None,
        timeout_override: Optional[float] = None,
        max_attempts_override: Optional[int] = None,
    ) -> str:
        """Send speech-to-text requests using OpenRouter's documented STT format."""

        headers = {
            "Authorization": f"Bearer {config.OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }

        payload = {
            "input_audio": {
                "data": base64.b64encode(audio_bytes).decode("ascii"),
                "format": _guess_audio_format(filename),
            },
            "model": config.OPENAI_TRANSCRIPTION_MODEL,
            "prompt": prompt or _build_chunk_transcription_prompt(),
        }

        response = self._post_with_retries(
            f"{config.OPENAI_BASE_URL.rstrip('/')}/audio/transcriptions",
            headers=headers,
            json=payload,
            timeout_override=timeout_override,
            max_attempts_override=max_attempts_override,
        )

        if response.status_code != 200:
            raise RuntimeError(
                f"Cloud transcription provider returned status {response.status_code}: {response.text}"
            )

        payload = response.json()
        text = payload.get("text", "")
        if not isinstance(text, str):
            text = str(text or "")
        return _apply_glossary_corrections(text.strip())

    def _transcribe_file_direct(self, file_path: Path) -> list[TranscriptSegment]:
        """Upload the original file directly when local decode tools are unavailable."""

        if _is_openrouter_base_url():
            return self._transcribe_file_direct_openrouter(file_path)

        endpoint = (
            "audio/translations"
            if config.WHISPER_TASK.lower() == "translate"
            else "audio/transcriptions"
        )
        headers = {"Authorization": f"Bearer {config.OPENAI_API_KEY}"}
        if config.OPENAI_PROJECT:
            headers["OpenAI-Project"] = config.OPENAI_PROJECT

        data = {
            "model": config.OPENAI_TRANSCRIPTION_MODEL,
            "response_format": "verbose_json",
            "prompt": _build_file_transcription_prompt(),
        }

        with file_path.open("rb") as audio_file:
            response = self._post_with_retries(
                f"{config.OPENAI_BASE_URL.rstrip('/')}/{endpoint}",
                headers=headers,
                data=data,
                files={"file": (file_path.name, audio_file, "application/octet-stream")},
            )

        if response.status_code != 200:
            raise RuntimeError(
                f"Cloud transcription provider returned status {response.status_code}: {response.text}"
            )

        payload = response.json()
        segments = payload.get("segments")
        if isinstance(segments, list) and segments:
            normalized_segments = []
            for segment in segments:
                text = _apply_glossary_corrections(str(segment.get("text", "")).strip())
                if not text or _is_hallucination_text(text):
                    continue
                duration = float(segment.get("end", 0.0) or 0.0) - float(segment.get("start", 0.0) or 0.0)
                confidence = _estimate_cloud_confidence(text, duration=duration)

                normalized_segments.append(
                    TranscriptSegment(
                        text=text,
                        start_time=float(segment.get("start", 0.0) or 0.0),
                        end_time=float(segment.get("end", 0.0) or 0.0),
                        confidence=confidence,
                        language="en" if config.WHISPER_TASK.lower() == "translate" else "",
                        is_unclear=confidence < config.CONFIDENCE_THRESHOLD,
                    )
                )

            if normalized_segments:
                return normalized_segments

        total_duration = self._extract_provider_duration(payload)
        text = _apply_glossary_corrections(str(payload.get("text", "") or "").strip())
        return self._build_segments_from_full_transcript(text, total_duration)

    def _transcribe_file_direct_openrouter(self, file_path: Path) -> list[TranscriptSegment]:
        """Upload the original file to OpenRouter's STT endpoint as base64 JSON."""

        headers = {
            "Authorization": f"Bearer {config.OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }

        with file_path.open("rb") as audio_file:
            audio_bytes = audio_file.read()

        payload = {
            "input_audio": {
                "data": base64.b64encode(audio_bytes).decode("ascii"),
                "format": _guess_audio_format(file_path.name),
            },
            "model": config.OPENAI_TRANSCRIPTION_MODEL,
            "prompt": _build_file_transcription_prompt(),
        }

        response = self._post_with_retries(
            f"{config.OPENAI_BASE_URL.rstrip('/')}/audio/transcriptions",
            headers=headers,
            json=payload,
        )

        if response.status_code != 200:
            raise RuntimeError(
                f"Cloud transcription provider returned status {response.status_code}: {response.text}"
            )

        payload = response.json()
        total_duration = self._extract_provider_duration(payload)
        text = _apply_glossary_corrections(str(payload.get("text", "") or "").strip())
        return self._build_segments_from_full_transcript(text, total_duration)

    def _post_with_retries(
        self,
        url: str,
        timeout_override: Optional[float] = None,
        max_attempts_override: Optional[int] = None,
        **kwargs,
    ) -> httpx.Response:
        """Retry transient upstream failures before surfacing an error."""

        last_response: Optional[httpx.Response] = None
        max_attempts = (
            max(1, int(max_attempts_override))
            if max_attempts_override is not None
            else max(1, config.OPENAI_TRANSCRIPTION_MAX_RETRIES + 1)
        )
        timeout = (
            float(timeout_override)
            if timeout_override is not None
            else float(config.OPENAI_TIMEOUT_SECONDS)
        )

        for attempt in range(1, max_attempts + 1):
            response = httpx.post(
                url,
                timeout=timeout,
                **kwargs,
            )
            if response.status_code not in {429, 502, 503, 504}:
                return response

            last_response = response
            if attempt < max_attempts:
                logger.warning(
                    "Transient transcription provider error %s on attempt %s/%s",
                    response.status_code,
                    attempt,
                    max_attempts,
                )
                time.sleep(min(1.5 * attempt, 4.0))

        return last_response

    def _build_segments_from_text(
        self,
        text: str,
        start_time: float,
        duration: float,
        confidence: Optional[float] = None,
    ) -> list[TranscriptSegment]:
        clean_text = _apply_glossary_corrections(text.strip())
        if not clean_text or _is_hallucination_text(clean_text):
            return []

        resolved_confidence = (
            _estimate_cloud_confidence(clean_text, duration=duration)
            if confidence is None
            else max(0.0, min(float(confidence), 1.0))
        )
        is_unclear = resolved_confidence < config.CONFIDENCE_THRESHOLD

        return [
            TranscriptSegment(
                text=clean_text,
                start_time=start_time,
                end_time=start_time + duration,
                confidence=resolved_confidence,
                language="en" if config.WHISPER_TASK.lower() == "translate" else "",
                is_unclear=is_unclear,
            )
        ]

    def _build_segments_from_full_transcript(
        self,
        text: str,
        total_duration: float,
    ) -> list[TranscriptSegment]:
        """Convert a full-file transcript into readable pseudo-segments."""

        chunks = self._polish_and_split_full_transcript(_apply_glossary_corrections(text))
        if not chunks:
            return []

        safe_duration = max(total_duration, float(len(chunks)))
        total_chars = max(sum(len(chunk) for chunk in chunks), 1)
        cursor = 0.0
        segments: list[TranscriptSegment] = []

        for index, chunk in enumerate(chunks):
            share = len(chunk) / total_chars
            remaining = max(safe_duration - cursor, 0.1)
            duration = remaining if index == len(chunks) - 1 else max(safe_duration * share, 1.0)
            confidence = _estimate_cloud_confidence(chunk, duration=duration)

            segments.append(
                TranscriptSegment(
                    text=chunk,
                    start_time=cursor,
                    end_time=min(cursor + duration, safe_duration),
                    confidence=confidence,
                    language="en" if config.WHISPER_TASK.lower() == "translate" else "",
                    is_unclear=confidence < config.CONFIDENCE_THRESHOLD,
                )
            )
            cursor = min(cursor + duration, safe_duration)

        return segments

    def _polish_and_split_full_transcript(self, text: str) -> list[str]:
        """Optionally run a text-only readability polish, then split into chunks."""

        cleaned = _apply_glossary_corrections(str(text or "").strip())
        if not cleaned:
            return []

        if (
            config.OPENAI_TRANSCRIPT_POLISH_ENABLED
            and len(cleaned) >= config.OPENAI_TRANSCRIPT_POLISH_MIN_CHARS
        ):
            polished = self._polish_full_transcript_with_model(cleaned)
            if polished:
                return polished

        return _split_transcript_into_readable_chunks(cleaned)

    def _polish_full_transcript_with_model(self, text: str) -> Optional[list[str]]:
        """Use the configured text model to restructure long transcripts without summarizing."""

        headers = {
            "Authorization": f"Bearer {config.OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }
        if config.OPENAI_PROJECT:
            headers["OpenAI-Project"] = config.OPENAI_PROJECT

        payload = {
            "model": config.SUMMARY_MODEL,
            "messages": [
                {"role": "system", "content": TRANSCRIPT_POLISH_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Rewrite this raw transcript into readable transcript segments while preserving every detail.\n\n"
                        f"{_build_glossary_prompt_block()}\n\n"
                        f"TRANSCRIPT:\n{text}"
                    ),
                },
            ],
            "response_format": {"type": "json_object"},
        }

        try:
            response = httpx.post(
                f"{config.OPENAI_BASE_URL.rstrip('/')}/chat/completions",
                headers=headers,
                json=payload,
                timeout=config.OPENAI_TIMEOUT_SECONDS,
            )
            if response.status_code != 200:
                logger.warning(
                    "Transcript polish request returned status %s; using deterministic split",
                    response.status_code,
                )
                return None

            data = response.json()
            content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
            if isinstance(content, list):
                content = "".join(
                    part.get("text", "") for part in content if isinstance(part, dict)
                )

            result = json.loads(content)
            segments = result.get("segments", [])
            if not isinstance(segments, list):
                return None

            cleaned_segments = []
            for segment in segments:
                normalized = _apply_glossary_corrections(
                    re.sub(r"\s+", " ", str(segment or "")).strip()
                )
                if normalized and not _is_hallucination_text(normalized):
                    cleaned_segments.append(normalized)

            return cleaned_segments or None
        except Exception as exc:
            logger.warning("Transcript polish failed; using deterministic split: %s", exc)
            return None

    def _extract_provider_duration(self, payload: dict) -> float:
        """Read duration metadata when the provider returns it."""

        usage = payload.get("usage")
        if isinstance(usage, dict):
            seconds = usage.get("seconds")
            try:
                if seconds is not None:
                    return max(float(seconds), 0.0)
            except (TypeError, ValueError):
                pass

        duration = payload.get("duration")
        try:
            if duration is not None:
                return max(float(duration), 0.0)
        except (TypeError, ValueError):
            pass

        return 0.0


class TranscriptionService:
    """Main transcription service with configurable provider selection."""

    def __init__(self, engine_name: Optional[str] = None):
        self._engine: Optional[BaseTranscriptionEngine] = None
        self._preferred_engine = (engine_name or config.TRANSCRIPTION_ENGINE).lower()

    def initialize(self):
        """Initialize the configured transcription engine."""

        engine_name = self._preferred_engine

        if engine_name == "openai":
            self._engine = OpenAITranscriptionEngine()
        elif engine_name == "faster-whisper":
            self._engine = LocalTranscriptionEngine()
        else:
            raise RuntimeError(
                f"Unsupported TRANSCRIBE_ENGINE `{engine_name}`."
            )

        self._engine.load_model()
        logger.info(
            "Transcription service initialized: engine=%s model=%s",
            self.engine_type,
            config.OPENAI_TRANSCRIPTION_MODEL
            if engine_name == "openai"
            else config.WHISPER_MODEL_SIZE,
        )

    def transcribe(
        self,
        audio_data: np.ndarray,
        time_offset: float = 0.0,
    ) -> list[TranscriptSegment]:
        if not self._engine:
            self.initialize()
        return self._engine.transcribe(audio_data, time_offset)

    def transcribe_file(self, file_path: str | Path) -> list[TranscriptSegment]:
        if not self._engine:
            self.initialize()
        return self._engine.transcribe_file(file_path)

    def normalize_live_segment(
        self,
        text: str,
        duration: float = 0.0,
        source_type: str = "",
        confidence: float = 0.0,
    ) -> tuple[str, bool]:
        """Translate/clean a live segment into English and optionally drop it."""

        cleaned = _apply_glossary_corrections(re.sub(r"\s+", " ", str(text or "")).strip())
        if not cleaned or _is_hallucination_text(cleaned):
            return "", True

        words = cleaned.split()
        non_ascii_chars = sum(1 for char in cleaned if ord(char) > 127)
        non_ascii_ratio = (non_ascii_chars / len(cleaned)) if cleaned else 0.0

        # For normal English live audio, never let a chat model rewrite the wording.
        # That can turn noisy Zoom chunks into fluent but incorrect sentences.
        if non_ascii_ratio < 0.08:
            # Keep weak but plausible live English chunks visible instead of
            # collapsing whole meetings to zero words. Only drop the most
            # obviously empty fragments.
            if confidence < 0.22 and len(words) <= 1:
                return "", True
            return cleaned, False

        # If the user wants conservative live translation only, keep risky mixed chunks raw
        # unless they are clearly non-English and reasonably confident.
        if config.LIVE_NORMALIZE_NON_ENGLISH_ONLY:
            if non_ascii_ratio < 0.18:
                if confidence < 0.24 and len(words) <= 1:
                    return "", True
                return cleaned, False

            # For clear non-English output we allow translation, but only when the
            # upstream speech model seemed reasonably sure there was actual speech.
            if confidence < 0.58 and len(words) <= 6:
                return "", True

        if not config.OPENAI_API_KEY:
            return cleaned, False

        headers = {
            "Authorization": f"Bearer {config.OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }
        if config.OPENAI_PROJECT:
            headers["OpenAI-Project"] = config.OPENAI_PROJECT

        payload = {
            "model": config.SUMMARY_MODEL,
            "messages": [
                {"role": "system", "content": LIVE_TRANSLATION_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"SOURCE TYPE: {source_type or 'unknown'}\n"
                        f"CONFIDENCE: {confidence:.3f}\n"
                        f"DURATION: {duration:.2f}\n"
                        f"{_build_glossary_prompt_block()}\n"
                        f"SEGMENT:\n{cleaned}"
                    ),
                },
            ],
            "response_format": {"type": "json_object"},
        }

        try:
            response = httpx.post(
                f"{config.OPENAI_BASE_URL.rstrip('/')}/chat/completions",
                headers=headers,
                json=payload,
                timeout=min(config.OPENAI_TIMEOUT_SECONDS, 20),
            )
            if response.status_code != 200:
                logger.warning(
                    "Live segment normalization failed with status %s; keeping raw text",
                    response.status_code,
                )
                return cleaned, False

            data = response.json()
            content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
            if isinstance(content, list):
                content = "".join(part.get("text", "") for part in content if isinstance(part, dict))

            result = json.loads(content)
            normalized = _apply_glossary_corrections(
                re.sub(r"\s+", " ", str(result.get("text", "") or "")).strip()
            )
            drop = bool(result.get("drop"))

            if drop or not normalized or _is_hallucination_text(normalized):
                return "", True

            # If the model still returns a mostly non-English fragment, reject weak segments.
            post_non_ascii = sum(1 for char in normalized if ord(char) > 127)
            post_ratio = (post_non_ascii / len(normalized)) if normalized else 0.0
            if post_ratio > 0.12 and confidence < 0.8:
                return "", True

            return normalized, False
        except Exception as exc:
            logger.warning("Live segment normalization failed; keeping raw text: %s", exc)
            return cleaned, False

    def normalize_uploaded_segment(
        self,
        text: str,
        duration: float = 0.0,
        confidence: float = 0.0,
        language: str = "",
    ) -> tuple[str, bool, bool]:
        """Review one uploaded-file segment for English cleanup and confidence-driven flags."""

        cleaned = _apply_glossary_corrections(re.sub(r"\s+", " ", str(text or "")).strip())
        if not cleaned or _is_hallucination_text(cleaned):
            return "", True, True

        if not config.OPENAI_API_KEY:
            review_needed = confidence < max(config.CONFIDENCE_THRESHOLD, 0.62)
            return cleaned, False, review_needed

        non_ascii_chars = sum(1 for char in cleaned if ord(char) > 127)
        non_ascii_ratio = (non_ascii_chars / len(cleaned)) if cleaned else 0.0
        if non_ascii_ratio < 0.05 and confidence >= 0.84 and len(cleaned.split()) >= 4:
            return cleaned, False, False

        headers = {
            "Authorization": f"Bearer {config.OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }
        if config.OPENAI_PROJECT:
            headers["OpenAI-Project"] = config.OPENAI_PROJECT

        payload = {
            "model": config.SUMMARY_MODEL,
            "messages": [
                {"role": "system", "content": FILE_SEGMENT_REVIEW_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"LANGUAGE HINT: {language or 'unknown'}\n"
                        f"CONFIDENCE: {confidence:.3f}\n"
                        f"DURATION: {duration:.2f}\n"
                        f"{_build_glossary_prompt_block()}\n"
                        f"SEGMENT:\n{cleaned}"
                    ),
                },
            ],
            "response_format": {"type": "json_object"},
        }

        try:
            response = httpx.post(
                f"{config.OPENAI_BASE_URL.rstrip('/')}/chat/completions",
                headers=headers,
                json=payload,
                timeout=min(config.OPENAI_TIMEOUT_SECONDS, 25),
            )
            if response.status_code != 200:
                logger.warning(
                    "Uploaded segment review failed with status %s; keeping raw text",
                    response.status_code,
                )
                review_needed = confidence < max(config.CONFIDENCE_THRESHOLD, 0.62)
                return cleaned, False, review_needed

            data = response.json()
            content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
            if isinstance(content, list):
                content = "".join(part.get("text", "") for part in content if isinstance(part, dict))

            result = json.loads(content)
            normalized = _apply_glossary_corrections(
                re.sub(r"\s+", " ", str(result.get("text", "") or "")).strip()
            )
            drop = bool(result.get("drop"))
            review = bool(result.get("review"))

            if drop or not normalized or _is_hallucination_text(normalized):
                return "", True, True

            return normalized, False, review or confidence < max(config.CONFIDENCE_THRESHOLD, 0.62)
        except Exception as exc:
            logger.warning("Uploaded segment review failed; keeping raw text: %s", exc)
            review_needed = confidence < max(config.CONFIDENCE_THRESHOLD, 0.62)
            return cleaned, False, review_needed

    @property
    def engine_type(self) -> str:
        if not self._engine:
            return self._preferred_engine
        return self._engine.provider_name
