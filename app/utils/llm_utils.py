from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any

from google.genai import types


IMAGE_MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


def encode_image_to_data_url(image_path: str | Path) -> str:
    """Return a base64 data URL for compatibility/debug use.

    Gemini calls in this codebase use `load_image_part_for_gemini` directly,
    but keeping this helper is useful for diagnostics and future REST fallbacks.
    """
    path = Path(image_path)
    mime_type = IMAGE_MIME_TYPES.get(path.suffix.lower())
    if not mime_type:
        raise ValueError(f"Unsupported image extension for base64 encoding: {path.suffix}")

    encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"


def load_image_part_for_gemini(image_path: str | Path) -> types.Part:
    """Load an image from disk as a Gemini inline image part."""
    path = Path(image_path)
    mime_type = IMAGE_MIME_TYPES.get(path.suffix.lower())
    if not mime_type:
        raise ValueError(f"Unsupported image extension for Gemini Vision: {path.suffix}")

    return types.Part.from_bytes(
        data=path.read_bytes(),
        mime_type=mime_type,
    )


def extract_json_from_text(text: str) -> dict[str, Any]:
    """Extract a JSON object from an LLM response string.

    The Gemini calls request `application/json`, but this parser is deliberately
    defensive so local tests, fallback mocks, or provider response wrappers do
    not break the pipeline.
    """
    cleaned = str(text or "").strip()

    if not cleaned:
        raise ValueError("LLM response is empty; expected JSON object.")

    try:
        parsed = json.loads(cleaned)
        if not isinstance(parsed, dict):
            raise ValueError("LLM response JSON must be an object.")
        return parsed
    except json.JSONDecodeError:
        pass

    fenced_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.DOTALL)
    if fenced_match:
        try:
            parsed = json.loads(fenced_match.group(1))
            if not isinstance(parsed, dict):
                raise ValueError("LLM response JSON must be an object.")
            return parsed
        except json.JSONDecodeError:
            pass

    object_match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if object_match:
        try:
            parsed = json.loads(object_match.group(0))
            if not isinstance(parsed, dict):
                raise ValueError("LLM response JSON must be an object.")
            return parsed
        except json.JSONDecodeError as exc:
            raise ValueError("Could not parse JSON object from LLM response.") from exc

    raise ValueError("Could not find JSON object in LLM response.")
