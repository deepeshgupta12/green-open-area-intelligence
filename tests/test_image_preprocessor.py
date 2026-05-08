from pathlib import Path

from app.services.image_preprocessor import preprocess_master_plan_image


def test_master_plan_image_preprocessor():
    image_path = Path("data/input/master_plan.png")

    assert image_path.exists(), "Expected data/input/master_plan.png to exist."

    metadata = preprocess_master_plan_image(str(image_path))

    assert metadata.file_name == "master_plan.png"
    assert metadata.file_extension == ".png"
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
