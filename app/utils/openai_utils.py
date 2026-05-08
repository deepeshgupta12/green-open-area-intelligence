import base64
import json
import re
from pathlib import Path


MIME_TYPE_BY_EXTENSION = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


def encode_image_to_data_url(image_path: str | Path) -> str:
    path = Path(image_path)

    if not path.exists():
        raise FileNotFoundError(f"Image file not found: {path}")

    suffix = path.suffix.lower()
    mime_type = MIME_TYPE_BY_EXTENSION.get(suffix)

    if not mime_type:
        raise ValueError(f"Unsupported image extension for OpenAI Vision: {suffix}")

    encoded = base64.b64encode(path.read_bytes()).decode("utf-8")

    return f"data:{mime_type};base64,{encoded}"


def extract_json_from_text(text: str) -> dict:
    """
    Extract JSON object from model text.

    Handles:
    - direct JSON
    - fenced ```json blocks
    - surrounding prose
    """
    cleaned = text.strip()

    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)

    if not match:
        raise ValueError("No JSON object found in OpenAI response.")

    return json.loads(match.group(0))
