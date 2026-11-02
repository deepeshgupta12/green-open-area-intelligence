"""Factory for the Gemini client shared by every LLM-backed service.

Two authentication modes are supported, checked in this order:

1. **Vertex AI with a Google Cloud service account.** Set
   ``GOOGLE_APPLICATION_CREDENTIALS`` to the service-account JSON path. The
   project id is read from that file unless ``GOOGLE_CLOUD_PROJECT`` overrides
   it, and ``GOOGLE_CLOUD_LOCATION`` picks the regional endpoint.
2. **Gemini Developer API with an API key.** Set ``GEMINI_API_KEY``.

Services should call :func:`get_gemini_client` instead of constructing
``genai.Client`` themselves so the auth mode lives in one place.
"""

from __future__ import annotations

from pathlib import Path

from google import genai
from google.oauth2 import service_account

from app.config import Settings, get_settings


_VERTEX_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]

MISSING_CREDENTIALS_MESSAGE = (
    "Gemini credentials are missing. In .env set GOOGLE_APPLICATION_CREDENTIALS to a "
    "service-account JSON path (Vertex AI) or GEMINI_API_KEY (Gemini Developer API)."
)


def get_gemini_client(settings: Settings | None = None) -> genai.Client:
    """Return a configured Gemini client, preferring Vertex AI when a key file is set."""
    settings = settings or get_settings()

    if settings.google_application_credentials:
        return _build_vertex_client(settings)

    if settings.gemini_api_key:
        return genai.Client(api_key=settings.gemini_api_key)

    raise ValueError(MISSING_CREDENTIALS_MESSAGE)


def _build_vertex_client(settings: Settings) -> genai.Client:
    key_path = Path(settings.google_application_credentials or "").expanduser()
    if not key_path.is_file():
        raise ValueError(
            f"GOOGLE_APPLICATION_CREDENTIALS points to a missing file: {key_path}"
        )

    credentials = service_account.Credentials.from_service_account_file(
        str(key_path),
        scopes=_VERTEX_SCOPES,
    )

    project = settings.google_cloud_project or credentials.project_id
    if not project:
        raise ValueError(
            "GOOGLE_CLOUD_PROJECT is not set and the service-account file has no project_id."
        )

    return genai.Client(
        vertexai=True,
        project=project,
        location=settings.google_cloud_location,
        credentials=credentials,
    )
