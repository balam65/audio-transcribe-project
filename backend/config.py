"""
Configuration module for the Meeting Transcription System.
Loads settings from environment variables with sensible defaults.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from project root
PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _auto_detect_device() -> str:
    """Auto-detect GPU availability. Returns 'cuda' if available, else 'cpu'."""
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
    except ImportError:
        pass
    # Also check via ctranslate2 (used by faster-whisper)
    try:
        import ctranslate2
        if "cuda" in ctranslate2.get_supported_compute_types("cuda"):
            return "cuda"
    except Exception:
        pass
    return "cpu"


def _auto_compute_type(device: str) -> str:
    """Pick optimal compute type based on device."""
    if device == "cuda":
        return "float16"
    return "int8"


class Config:
    """Central configuration class for configurable transcription and summaries."""

    # --- App Mode / Authentication ---
    APP_MODE: str = os.getenv("APP_MODE", "desktop").lower()
    AUTH_REQUIRED: bool = os.getenv(
        "AUTH_REQUIRED",
        "true" if APP_MODE == "hosted" else "false",
    ).lower() == "true"
    AUTH_USERNAME: str = os.getenv("AUTH_USERNAME", "admin")
    AUTH_PASSWORD: str = os.getenv("AUTH_PASSWORD", "")
    SESSION_SECRET: str = os.getenv("SESSION_SECRET", "")
    PUBLIC_BASE_URL: str = os.getenv("PUBLIC_BASE_URL", "").strip()

    # --- Transcription Engine ---
    TRANSCRIPTION_ENGINE: str = os.getenv("TRANSCRIBE_ENGINE", "openai").lower()

    # --- Whisper Model ---
    WHISPER_MODEL_SIZE: str = os.getenv("WHISPER_MODEL", "large-v3")
    WHISPER_TASK: str = os.getenv("WHISPER_TASK", "translate")
    WHISPER_OUTPUT_LANGUAGE: str = os.getenv("WHISPER_OUTPUT_LANGUAGE", "en")
    OPENAI_TRANSCRIPTION_MODEL: str = os.getenv("OPENAI_TRANSCRIPTION_MODEL", "gpt-4o-mini-transcribe")
    OPENAI_TRANSCRIPTION_CHUNK_SECONDS: int = int(os.getenv("OPENAI_TRANSCRIPTION_CHUNK_SECONDS", "20"))
    OPENAI_UPLOAD_CHUNK_SECONDS: int = int(os.getenv("OPENAI_UPLOAD_CHUNK_SECONDS", "75"))
    OPENAI_UPLOAD_CHUNK_OVERLAP_SECONDS: int = int(os.getenv("OPENAI_UPLOAD_CHUNK_OVERLAP_SECONDS", "4"))
    TRANSCRIPTION_GLOSSARY_PATH: str = os.getenv(
        "TRANSCRIPTION_GLOSSARY_PATH",
        "data/transcription_glossary.txt",
    )
    OPENAI_TRANSCRIPTION_MAX_RETRIES: int = int(os.getenv("OPENAI_TRANSCRIPTION_MAX_RETRIES", "2"))
    OPENAI_TRANSCRIPT_POLISH_ENABLED: bool = os.getenv("OPENAI_TRANSCRIPT_POLISH", "true").lower() == "true"
    OPENAI_TRANSCRIPT_POLISH_MIN_CHARS: int = int(os.getenv("OPENAI_TRANSCRIPT_POLISH_MIN_CHARS", "600"))
    OPENAI_TRANSCRIPTION_PROMPT: str = os.getenv(
        "OPENAI_TRANSCRIPTION_PROMPT",
        (
            "Transcribe the speech clearly and accurately. "
            "If speakers use multiple languages, translate everything into natural English. "
            "Preserve names, numbers, technical terms, and meaning exactly. "
            "Do not summarize, shorten, or omit spoken details."
        ),
    )

    # Device & compute — resolved at runtime in validate()
    _WHISPER_DEVICE_RAW: str = os.getenv("WHISPER_DEVICE", "auto")
    _WHISPER_COMPUTE_RAW: str = os.getenv("WHISPER_COMPUTE_TYPE", "auto")
    WHISPER_DEVICE: str = ""  # Set in validate()
    WHISPER_COMPUTE_TYPE: str = ""  # Set in validate()

    # --- Audio Settings ---
    AUDIO_CHUNK_DURATION: int = int(os.getenv("AUDIO_CHUNK_SECONDS", "6"))
    AUDIO_CHUNK_STEP_DURATION: float = float(os.getenv("AUDIO_CHUNK_STEP_SECONDS", "3"))
    SAMPLE_RATE: int = 16000  # 16kHz mono — optimal for Whisper
    CHANNELS: int = 1
    AUDIO_FORMAT_WIDTH: int = 2  # 16-bit PCM
    LIVE_MIN_RMS: float = float(os.getenv("LIVE_MIN_RMS", "0.004"))
    LIVE_MIN_PEAK: float = float(os.getenv("LIVE_MIN_PEAK", "0.025"))
    LIVE_TRANSCRIPTION_TIMEOUT_SECONDS: float = float(
        os.getenv("LIVE_TRANSCRIPTION_TIMEOUT_SECONDS", "12")
    )
    LIVE_TRANSCRIPTION_MAX_RETRIES: int = int(
        os.getenv("LIVE_TRANSCRIPTION_MAX_RETRIES", "0")
    )
    LIVE_NORMALIZE_NON_ENGLISH_ONLY: bool = (
        os.getenv("LIVE_NORMALIZE_NON_ENGLISH_ONLY", "true").lower() == "true"
    )

    # --- Speaker Diarization ---
    ENABLE_DIARIZATION: bool = os.getenv("ENABLE_DIARIZATION", "false").lower() == "true"

    # --- Accuracy / Anti-Hallucination ---
    CONFIDENCE_THRESHOLD: float = float(os.getenv("CONFIDENCE_THRESHOLD", "0.45"))
    NO_SPEECH_THRESHOLD: float = float(os.getenv("NO_SPEECH_THRESHOLD", "0.45"))

    # --- Server ---
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))

    # --- Summary Provider ---
    SUMMARY_ENGINE: str = os.getenv("SUMMARY_ENGINE", "openai").lower()
    SUMMARY_MODEL: str = os.getenv("SUMMARY_MODEL", "gpt-5.4-mini")
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    OPENAI_PROJECT: str = os.getenv("OPENAI_PROJECT", "")
    OPENAI_REASONING_EFFORT: str = os.getenv("OPENAI_REASONING_EFFORT", "low")
    OPENAI_TIMEOUT_SECONDS: float = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "120"))

    # --- Storage ---
    DATABASE_PATH: str = os.getenv("DATABASE_PATH", "data/meetings.db")
    EXPORT_DIR: str = os.getenv("EXPORT_DIR", "data/exports")
    LOCAL_RECORDING_DIR: str = os.getenv("LOCAL_RECORDING_DIR", "data/local_recordings")

    @classmethod
    def get_db_path(cls) -> Path:
        """Get the absolute path to the database file."""
        path = PROJECT_ROOT / cls.DATABASE_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    @classmethod
    def get_export_dir(cls) -> Path:
        """Get the absolute path to the export directory."""
        path = PROJECT_ROOT / cls.EXPORT_DIR
        path.mkdir(parents=True, exist_ok=True)
        return path

    @classmethod
    def get_local_recording_dir(cls) -> Path:
        """Get the absolute path to the local recording directory."""
        path = PROJECT_ROOT / cls.LOCAL_RECORDING_DIR
        path.mkdir(parents=True, exist_ok=True)
        return path

    @classmethod
    def get_transcription_glossary_path(cls) -> Path:
        """Get the absolute path to the optional transcription glossary file."""
        path = PROJECT_ROOT / cls.TRANSCRIPTION_GLOSSARY_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    @classmethod
    def validate(cls):
        """Resolve auto settings and print configuration summary."""
        # --- Resolve device ---
        if cls._WHISPER_DEVICE_RAW == "auto":
            cls.WHISPER_DEVICE = _auto_detect_device()
        else:
            cls.WHISPER_DEVICE = cls._WHISPER_DEVICE_RAW

        # --- Resolve compute type ---
        if cls._WHISPER_COMPUTE_RAW == "auto":
            cls.WHISPER_COMPUTE_TYPE = _auto_compute_type(cls.WHISPER_DEVICE)
        else:
            cls.WHISPER_COMPUTE_TYPE = cls._WHISPER_COMPUTE_RAW

        # --- Print config ---
        gpu_label = "🟢 GPU (CUDA)" if cls.WHISPER_DEVICE == "cuda" else "🔵 CPU"
        print(f"  🎧 Transcription engine: {cls.TRANSCRIPTION_ENGINE}")
        print(f"  🏷️  App mode: {cls.APP_MODE}")
        if cls.TRANSCRIPTION_ENGINE == "openai":
            print(f"  🤖 OpenAI transcription model: {cls.OPENAI_TRANSCRIPTION_MODEL}")
        else:
            print(f"  📦 Whisper model: {cls.WHISPER_MODEL_SIZE}")
        print(f"  💻 Device: {gpu_label}, Compute: {cls.WHISPER_COMPUTE_TYPE}")
        print(f"  🌐 Task: {cls.WHISPER_TASK} → {cls.WHISPER_OUTPUT_LANGUAGE}")
        print(f"  🧠 Summary: {cls.SUMMARY_ENGINE} ({cls.SUMMARY_MODEL})")
        print(f"  📊 Anti-hallucination: confidence≥{cls.CONFIDENCE_THRESHOLD}, "
              f"no_speech≤{cls.NO_SPEECH_THRESHOLD}")
        print(
            "  🔐 Auth: "
            + (
                f"enabled for `{cls.AUTH_USERNAME}`"
                if cls.auth_configured()
                else ("enabled but not configured" if cls.AUTH_REQUIRED else "disabled")
            )
        )
        print(
            "  🎛️  Capabilities: "
            f"live_capture={'yes' if cls.live_capture_enabled() else 'no'}, "
            f"local_recording={'yes' if cls.local_recording_enabled() else 'no'}, "
            f"file_upload={'yes' if cls.file_upload_enabled() else 'no'}"
        )

        if cls.TRANSCRIPTION_ENGINE == "openai":
            if cls.OPENAI_API_KEY:
                print("  ✅ OpenAI-compatible transcription provider configured")
            else:
                print("  ⚠️  OPENAI_API_KEY is missing — cloud transcription will not work")

        if cls.SUMMARY_ENGINE == "openai":
            if cls.OPENAI_API_KEY:
                base_url = cls.OPENAI_BASE_URL.rstrip("/")
                print(f"  ✅ OpenAI-compatible summary provider configured at {base_url}")
            else:
                print("  ⚠️  OPENAI_API_KEY is missing — fallback summaries will be used")
        elif cls.SUMMARY_ENGINE == "ollama":
            try:
                import httpx

                resp = httpx.get(f"{cls.OLLAMA_BASE_URL}/api/tags", timeout=3)
                if resp.status_code == 200:
                    models = resp.json().get("models", [])
                    model_names = {
                        (model.get("name") or model.get("model") or "").split(":")[0]
                        for model in models
                    }
                    if cls.SUMMARY_MODEL.split(":")[0] in model_names:
                        print(f"  ✅ Ollama is running at {cls.OLLAMA_BASE_URL}")
                    else:
                        print(
                            f"  ⚠️  Ollama is running but model `{cls.SUMMARY_MODEL}` is not installed"
                        )
                else:
                    print(f"  ⚠️  Ollama responded with status {resp.status_code}")
            except Exception:
                print(
                    f"  ⚠️  Ollama not reachable at {cls.OLLAMA_BASE_URL} — fallback summaries will be used"
                )
        else:
            print(
                f"  ⚠️  Unsupported SUMMARY_ENGINE `{cls.SUMMARY_ENGINE}` — fallback summaries will be used"
            )

        if cls.AUTH_REQUIRED and not cls.auth_configured():
            print(
                "  ⚠️  AUTH_REQUIRED is enabled, but AUTH_PASSWORD or SESSION_SECRET is missing"
            )

        return True

    @classmethod
    def hosted_mode(cls) -> bool:
        """Whether the app is running as a hosted/public deployment."""
        return cls.APP_MODE == "hosted"

    @classmethod
    def live_capture_enabled(cls) -> bool:
        """Live capture requires local audio access and is disabled in hosted mode."""
        return not cls.hosted_mode()

    @classmethod
    def local_recording_enabled(cls) -> bool:
        """Backend WAV recording also requires local audio access."""
        return not cls.hosted_mode()

    @classmethod
    def file_upload_enabled(cls) -> bool:
        """Uploaded-file transcription is safe in both desktop and hosted modes."""
        return True

    @classmethod
    def auth_configured(cls) -> bool:
        """Server-side auth requires both a password and a session secret."""
        if not cls.AUTH_REQUIRED:
            return True
        return bool(cls.AUTH_USERNAME and cls.AUTH_PASSWORD and cls.SESSION_SECRET)

    @classmethod
    def capabilities(cls) -> dict:
        """Expose frontend/backend capability flags in one place."""
        return {
            "live_capture": cls.live_capture_enabled(),
            "local_recording": cls.local_recording_enabled(),
            "file_upload": cls.file_upload_enabled(),
        }


config = Config()
