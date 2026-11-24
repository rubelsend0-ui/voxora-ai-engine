"""Application settings, loaded from environment variables (prefix ``VOXORA_``)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_PEPPER = "change-me-in-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VOXORA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- general ---------------------------------------------------------
    app_name: str = "VOXORA AI Engine"
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    docs_enabled: bool = True

    # --- database --------------------------------------------------------
    database_url: str = "sqlite:///./data/voxora.db"
    # Dev convenience for SQLite. With PostgreSQL run `alembic upgrade head`.
    auto_create_tables: bool = False

    # --- filesystem (models are stored separately from user media) -------
    data_dir: Path = Path("./data")
    storage_dir: Path | None = None
    models_dir: Path | None = None
    tmp_dir: Path | None = None

    # --- security --------------------------------------------------------
    api_key_pepper: str = INSECURE_PEPPER
    cors_origins: str = ""  # comma separated; empty = CORS disabled
    max_upload_mb: int = 500  # media uploads (audio/video)
    max_voice_sample_mb: int = 50
    rate_limit_per_minute: int = 120
    rate_limit_heavy_per_minute: int = 12  # job-creating endpoints
    auth_fail_limit_per_minute: int = 20  # per client IP
    redis_url: str | None = None  # enables shared rate limiting + celery

    # --- jobs ------------------------------------------------------------
    # local  : in-process thread pool (simple single-node deployments)
    # celery : Redis + Celery workers (scalable)
    # inline : run synchronously inside the request (tests / debugging only)
    job_backend: Literal["local", "celery", "inline"] = "local"
    local_workers: int = 1
    celery_broker_url: str | None = None
    celery_result_backend: str | None = None

    # --- AI engines (adapters are replaceable) ---------------------------
    device: Literal["auto", "cpu", "cuda"] = "auto"
    voice_cloning_adapter: str = "xtts_v2"
    tts_adapter: str = "xtts_v2"
    stt_adapter: str = "faster_whisper"
    translation_adapter: str = "marian"
    audio_adapter: str = "ffmpeg"
    dubbing_adapter: str = "pipeline"
    whisper_model_size: str = "small"
    whisper_compute_type: str = "auto"
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"

    # --- limits ----------------------------------------------------------
    max_text_chars: int = 5000
    max_translation_chars: int = 20000
    voice_min_seconds: float = 6.0
    voice_max_seconds: float = 300.0
    voice_min_speech_seconds: float = 5.0
    voice_reference_max_seconds: float = 30.0
    media_max_seconds: float = 3600.0
    dubbing_max_seconds: float = 1800.0
    dubbing_max_speedup: float = 1.4

    # --- derived paths ---------------------------------------------------
    @property
    def storage_root(self) -> Path:
        return (self.storage_dir or self.data_dir / "storage").resolve()

    @property
    def models_root(self) -> Path:
        return (self.models_dir or self.data_dir / "models").resolve()

    @property
    def tmp_root(self) -> Path:
        return (self.tmp_dir or self.data_dir / "tmp").resolve()

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def max_voice_sample_bytes(self) -> int:
        return self.max_voice_sample_mb * 1024 * 1024

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def effective_celery_broker(self) -> str | None:
        return self.celery_broker_url or self.redis_url

    @property
    def effective_celery_backend(self) -> str | None:
        return self.celery_result_backend or self.redis_url

    @model_validator(mode="after")
    def _validate(self) -> Settings:
        if self.environment == "production":
            if self.api_key_pepper == INSECURE_PEPPER or len(self.api_key_pepper) < 32:
                raise ValueError(
                    "VOXORA_API_KEY_PEPPER must be set to a random string of at least "
                    "32 characters in production."
                )
        if self.job_backend == "celery" and not self.effective_celery_broker:
            raise ValueError("job_backend=celery requires VOXORA_REDIS_URL or VOXORA_CELERY_BROKER_URL.")
        if self.local_workers < 1:
            raise ValueError("VOXORA_LOCAL_WORKERS must be >= 1")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
