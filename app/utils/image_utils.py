from pathlib import Path

import cv2
import numpy as np
from PIL import Image


SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def validate_image_path(image_path: str | Path) -> Path:
    path = Path(image_path)

    if not path.exists():
        raise FileNotFoundError(f"Image file not found: {path}")

    if not path.is_file():
        raise ValueError(f"Image path is not a file: {path}")

    if path.suffix.lower() not in SUPPORTED_IMAGE_EXTENSIONS:
        raise ValueError(
            f"Unsupported image format: {path.suffix}. "
            f"Supported formats: {sorted(SUPPORTED_IMAGE_EXTENSIONS)}"
        )

    return path


def get_file_size_mb(file_path: str | Path) -> float:
    path = Path(file_path)
    return round(path.stat().st_size / (1024 * 1024), 4)


def load_image_with_pillow(image_path: str | Path) -> Image.Image:
    path = validate_image_path(image_path)

    try:
        image = Image.open(path)
        image.load()
        return image
    except Exception as exc:
        raise ValueError(f"Unable to load image using Pillow: {path}") from exc


def load_image_with_cv2(image_path: str | Path) -> np.ndarray:
    path = validate_image_path(image_path)

    image = cv2.imread(str(path), cv2.IMREAD_COLOR)

    if image is None:
        raise ValueError(f"Unable to load image using OpenCV: {path}")

    return image


def save_normalized_png(
    source_image_path: str | Path,
    output_image_path: str | Path,
    max_dimension: int = 1800,
) -> Path:
    source_path = validate_image_path(source_image_path)
    output_path = Path(output_image_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    image = load_image_with_pillow(source_path).convert("RGB")
    width, height = image.size

    largest_side = max(width, height)

    if largest_side > max_dimension:
        scale = max_dimension / largest_side
        new_width = int(width * scale)
        new_height = int(height * scale)
        image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)

    image.save(output_path, format="PNG", optimize=True)

    return output_path


def calculate_laplacian_variance(image_path: str | Path) -> float:
    image = load_image_with_cv2(image_path)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    variance = cv2.Laplacian(gray, cv2.CV_64F).var()
    return round(float(variance), 4)


def calculate_brightness_score(image_path: str | Path) -> float:
    image = load_image_with_cv2(image_path)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    brightness = hsv[:, :, 2].mean()
    return round(float(brightness), 4)


def calculate_colorfulness_score(image_path: str | Path) -> float:
    image = load_image_with_cv2(image_path).astype("float")

    blue, green, red = cv2.split(image)

    rg = np.absolute(red - green)
    yb = np.absolute(0.5 * (red + green) - blue)

    std_rg = np.std(rg)
    std_yb = np.std(yb)
    mean_rg = np.mean(rg)
    mean_yb = np.mean(yb)

    colorfulness = np.sqrt(std_rg**2 + std_yb**2) + 0.3 * np.sqrt(mean_rg**2 + mean_yb**2)

    return round(float(colorfulness), 4)
