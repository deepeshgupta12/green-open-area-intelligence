from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Central application settings.

    Values are loaded from `.env` when present. Defaults are safe for local
    development and CLI-based execution.
    """

    app_name: str = "Green Open Area Intelligence Engine"
    app_env: str = "local"

    openai_api_key: str | None = None
    openai_vision_model: str = "gpt-4o"
    openai_text_model: str = "gpt-4o-mini"

    database_url: str = "sqlite:///./goa_engine.sqlite3"

    max_image_size_mb: int = 15
    default_confidence_threshold: float = 0.65

    project_root: Path = Path(__file__).resolve().parent.parent
    data_input_dir: Path = project_root / "data" / "input"
    data_output_dir: Path = project_root / "data" / "output"
    data_output_json_dir: Path = project_root / "data" / "output" / "json"
    data_output_reports_dir: Path = project_root / "data" / "output" / "reports"
    data_output_overlays_dir: Path = project_root / "data" / "output" / "overlays"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
