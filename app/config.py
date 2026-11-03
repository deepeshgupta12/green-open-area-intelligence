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

    # Gemini auth. Either a Vertex AI service-account key file (preferred when
    # set) or a Gemini Developer API key. See app/utils/gemini_client.py.
    google_application_credentials: str | None = None
    google_cloud_project: str | None = None
    google_cloud_location: str = "global"
    gemini_api_key: str | None = None

    gemini_vision_model: str = "gemini-3.5-flash"
    gemini_text_model: str = "gemini-3.5-flash"

    database_url: str = "sqlite:///./goa_engine.sqlite3"

    max_image_size_mb: int = 15

    # Backend QA agents: reviewer -> fixer -> reviewer loop after extraction,
    # and the teacher that maintains their playbook. Nothing reaches the UI.
    qa_agents_enabled: bool = True
    qa_max_rounds: int = 2
    qa_teacher_enabled: bool = True
    qa_playbook_path: str = "data/agents/playbook.json"
    default_confidence_threshold: float = 0.65

    # Density benchmark dataset for the site metrics dashboards. The default
    # is a clearly labelled synthetic sample; point this at a Datacenter export.
    density_benchmarks_path: str = "data/benchmarks/density_benchmarks.sample.json"

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

    @property
    def gemini_configured(self) -> bool:
        """True when either Gemini auth mode has credentials available."""
        return bool(self.google_application_credentials or self.gemini_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
