from pathlib import Path

from app.services.image_preprocessor import preprocess_master_plan_image


def find_master_plan_image() -> Path:
    candidates = [
        Path("data/input/master_plan.jpg"),
        Path("data/input/master_plan.jpeg"),
        Path("data/input/master_plan.png"),
        Path("data/input/master_plan.webp"),
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    raise AssertionError(
        "Expected one master plan image to exist in data/input with extension "
        ".jpg, .jpeg, .png, or .webp."
    )


def test_master_plan_image_preprocessor():
    image_path = find_master_plan_image()

    metadata = preprocess_master_plan_image(str(image_path))

    assert metadata.file_name == image_path.name
    assert metadata.file_extension == image_path.suffix.lower()
    assert metadata.file_size_mb > 0
    assert metadata.is_supported_format is True
    assert metadata.dimensions.width > 0
    assert metadata.dimensions.height > 0
    assert metadata.dimensions.total_pixels == (
        metadata.dimensions.width * metadata.dimensions.height
    )
    assert metadata.normalized_image_path is not None
    assert Path(metadata.normalized_image_path).exists()
    assert metadata.quality.score >= 0
    assert metadata.quality.label in {"High", "Medium", "Low", "Insufficient"}
    assert len(metadata.quality.reasons) > 0
