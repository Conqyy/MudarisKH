"""
Centralised application settings — loaded once from ``.env`` via dotenv.

Usage::

    from src.config.settings import settings, Settings
    print(settings.OPENROUTER_API_KEY)

    # For testing — override any value:
    test_cfg = Settings(openrouter_api_key="sk-test")
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    """Application settings populated from environment variables."""

    def __init__(self, **overrides):
        self.OPENROUTER_API_KEY = overrides.get(
            "openrouter_api_key", os.getenv("OPENROUTER_API_KEY", "")
        )
        self.OPENROUTER_BASE_URL = overrides.get(
            "openrouter_base_url",
            os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        )
        # Model id used for all OpenRouter calls. Prefer OPENROUTER_MODEL
        # (current var), fall back to legacy DEEPSEEK_MODEL_ID, then a default.
        self.OPENROUTER_MODEL = overrides.get(
            "openrouter_model",
            os.getenv("OPENROUTER_MODEL")
            or os.getenv("DEEPSEEK_MODEL_ID")
            or "google/gemini-3.1-pro-preview",
        )
        # Backward-compatible alias — the agent reads settings.DEEPSEEK_MODEL_ID
        self.DEEPSEEK_MODEL_ID = self.OPENROUTER_MODEL
        self.FIREBASE_KEY_PATH = overrides.get(
            "firebase_key_path",
            os.getenv("FIREBASE_KEY_PATH", "src/config/firebase-key.json"),
        )
        self.STORAGE_BUCKET = overrides.get(
            "storage_bucket", os.getenv("STORAGE_BUCKET")
        )
        # Transcription is done by Groq's hosted Whisper-large-v3 (no local model).
        self.GROQ_API_KEY = overrides.get(
            "groq_api_key", os.getenv("GROQ_API_KEY", "")
        ).strip()
        self.GROQ_WHISPER_MODEL = overrides.get(
            "groq_whisper_model",
            os.getenv("GROQ_WHISPER_MODEL", "whisper-large-v3"),
        ).strip()
        # Optional: force the spoken language (e.g. "ar", "en"). Empty = auto-detect.
        self.WHISPER_LANGUAGE = overrides.get(
            "whisper_language", os.getenv("WHISPER_LANGUAGE", "")
        ).strip()
        # Cap output tokens so OpenRouter doesn't reserve the model's full
        # context (e.g. 65536) per request, which over-charges credits.
        self.OPENROUTER_MAX_TOKENS = int(overrides.get(
            "openrouter_max_tokens",
            os.getenv("OPENROUTER_MAX_TOKENS", "8192"),
        ))


# Module-level singleton — importable as `from src.config.settings import settings`
settings = Settings()

# Also expose as module-level variables for backward compatibility.
# Supports:  from src.config import settings;  settings.OPENROUTER_API_KEY
OPENROUTER_API_KEY = settings.OPENROUTER_API_KEY
OPENROUTER_BASE_URL = settings.OPENROUTER_BASE_URL
OPENROUTER_MODEL = settings.OPENROUTER_MODEL
OPENROUTER_MAX_TOKENS = settings.OPENROUTER_MAX_TOKENS
DEEPSEEK_MODEL_ID = settings.DEEPSEEK_MODEL_ID
FIREBASE_KEY_PATH = settings.FIREBASE_KEY_PATH
STORAGE_BUCKET = settings.STORAGE_BUCKET
WHISPER_LANGUAGE = settings.WHISPER_LANGUAGE
GROQ_API_KEY = settings.GROQ_API_KEY
GROQ_WHISPER_MODEL = settings.GROQ_WHISPER_MODEL