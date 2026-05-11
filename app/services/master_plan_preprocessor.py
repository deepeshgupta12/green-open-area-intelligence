from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops

from app.config import get_settings
from app.schemas.image_schema import ImageMetadata
from app.schemas.master_plan_understanding_schema import MasterPlanPreprocessingArtifact


def create_master_plan_preprocessing_artifacts(
    image_metadata: ImageMetadata,
    project_id: str,
    output_dir: Path | None = None,
) -> list[MasterPlanPreprocessingArtifact]:
    """Create lightweight plan/legend crops for better downstream interpretation.

    This is intentionally conservative: it does not claim precise geometry. It
    removes obvious white margins and creates two helpful crops that OpenAI can
    use later: a plan-focused crop and a lower legend-focused crop.
    """
    settings = get_settings()
    base_dir = output_dir or settings.data_output_overlays_dir
    base_dir.mkdir(parents=True, exist_ok=True)

    source_path = Path(image_metadata.normalized_image_path or image_metadata.image_path)
    image = Image.open(source_path).convert("RGB")

    plan_crop_path = base_dir / f"{project_id}_plan_region_crop.png"
    legend_crop_path = base_dir / f"{project_id}_legend_region_crop.png"
    cleaned_path = base_dir / f"{project_id}_cleaned_plan_input.png"

    cropped = _crop_non_white_region(image)
    cropped.save(cleaned_path)

    width, height = cropped.size
    plan_region = cropped.crop((0, 0, width, int(height * 0.72)))
    legend_region = cropped.crop((0, int(height * 0.62), width, height))

    plan_region.save(plan_crop_path)
    legend_region.save(legend_crop_path)

    return [
        MasterPlanPreprocessingArtifact(
            artifact_type="cleaned_master_plan_input",
            path=str(cleaned_path),
            description="White-margin-reduced master plan input for structure extraction.",
        ),
        MasterPlanPreprocessingArtifact(
            artifact_type="plan_region_crop",
            path=str(plan_crop_path),
            description="Approximate plan-focused crop used for visual interpretation.",
        ),
        MasterPlanPreprocessingArtifact(
            artifact_type="legend_region_crop",
            path=str(legend_crop_path),
            description="Approximate lower legend/details crop used for legend extraction.",
        ),
    ]


def _crop_non_white_region(image: Image.Image) -> Image.Image:
    background = Image.new(image.mode, image.size, (255, 255, 255))
    diff = ImageChops.difference(image, background)
    bbox = diff.getbbox()
    if bbox is None:
        return image

    left, top, right, bottom = bbox
    padding_x = max(8, int(image.width * 0.015))
    padding_y = max(8, int(image.height * 0.015))

    left = max(0, left - padding_x)
    top = max(0, top - padding_y)
    right = min(image.width, right + padding_x)
    bottom = min(image.height, bottom + padding_y)

    return image.crop((left, top, right, bottom))
