import json
from pathlib import Path
from typing import Any


def ensure_directory(path: str | Path) -> Path:
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def read_json_file(file_path: str | Path) -> dict[str, Any]:
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"JSON file not found: {path}")

    if path.suffix.lower() != ".json":
        raise ValueError(f"Expected a .json file, received: {path}")

    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json_file(file_path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(file_path)
    ensure_directory(path.parent)

    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, ensure_ascii=False)

    return path


def safe_get_nested(data: dict[str, Any], keys: list[str], default: Any = None) -> Any:
    current: Any = data

    for key in keys:
        if not isinstance(current, dict):
            return default

        current = current.get(key)

        if current is None:
            return default

    return current


def strip_html_tags(value: str | None) -> str:
    if not value:
        return ""

    import re

    clean_text = re.sub(r"<[^>]+>", " ", value)
    clean_text = re.sub(r"\s+", " ", clean_text)
    return clean_text.strip()
