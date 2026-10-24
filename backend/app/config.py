from pathlib import Path
from ipaddress import ip_address
from urllib.parse import urlparse

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:4b"
    ollama_timeout_seconds: float = 180.0
    ollama_connect_timeout_seconds: float = 5.0
    ollama_num_ctx: int = 4096
    ollama_num_predict: int = 512
    ollama_keep_alive: str = "5m"
    max_upload_mb: int = 10
    max_text_chars: int = 100_000
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @field_validator("ollama_url")
    @classmethod
    def require_local_ollama(cls, value: str) -> str:
        parsed = urlparse(value)
        host = parsed.hostname or ""
        try:
            loopback = ip_address(host).is_loopback
        except ValueError:
            loopback = host.lower() == "localhost"
        if parsed.scheme not in {"http", "https"} or not loopback:
            raise ValueError("OLLAMA_URL must point to localhost or a loopback IP; remote inference is not supported.")
        return value.rstrip("/")

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
