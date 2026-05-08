from pathlib import Path

from app.services.image_preprocessor import preprocess_master_plan_image
from app.services.segmentation_engine import run_opencv_segmentation


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


def test_opencv_segmentation_engine():
    image_path = find_master_plan_image()
    image_metadata = preprocess_master_plan_image(str(image_path))

    result = run_opencv_segmentation(
        image_metadata=image_metadata,
        project_id="342956",
    )

    assert result.image_width > 0
    assert result.image_height > 0
    assert result.total_pixels == result.image_width * result.image_height

    assert len(result.classes) == 5

    total_percentage = sum(item.percentage for item in result.classes)

    assert 99.0 <= total_percentage <= 101.0

    for item in result.classes:
        assert item.pixel_count >= 0
        assert 0 <= item.percentage <= 100
        assert item.description

    assert Path(result.output_paths.overlay_path).exists()
    assert Path(result.output_paths.green_mask_path).exists()
    assert Path(result.output_paths.water_mask_path).exists()
    assert Path(result.output_paths.built_mask_path).exists()
    assert Path(result.output_paths.paved_mask_path).exists()
