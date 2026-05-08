from pathlib import Path

from PIL import Image

from app.config import get_settings
from app.schemas.image_schema import (
    ImageDimensions,
    ImageMetadata,
    ImageQualityAssessment,
)
from app.utils.image_utils import (
    calculate_brightness_score,
    calculate_colorfulness_score,
    calculate_laplacian_variance,
    get_file_size_mb,
    save_normalized_png,
    validate_image_path,
)


def preprocess_master_plan_image(image_path: str) -> ImageMetadata:
    settings = get_settings()

    source_path = validate_image_path(image_path)
    file_size_mb = get_file_size_mb(source_path)
    is_within_size_limit = file_size_mb <= settings.max_image_size_mb

    normalized_output_path = (
        settings.data_output_overlays_dir / f"{source_path.stem}_normalized.png"
    )

    normalized_path = save_normalized_png(
        source_image_path=source_path,
        output_image_path=normalized_output_path,
    )

    with Image.open(normalized_path) as normalized_image:
        width, height = normalized_image.size
        image_format = normalized_image.format
        image_mode = normalized_image.mode

    dimensions = ImageDimensions(
        width=width,
        height=height,
        total_pixels=width * height,
    )

    quality = assess_image_quality(
        image_path=str(normalized_path),
        dimensions=dimensions,
        file_size_mb=file_size_mb,
        is_within_size_limit=is_within_size_limit,
    )

    warnings: list[str] = []

    if not is_within_size_limit:
        warnings.append(
            f"Image size {file_size_mb} MB exceeds configured limit of "
            f"{settings.max_image_size_mb} MB."
        )

    if dimensions.width < 700 or dimensions.height < 500:
        warnings.append(
            "Image resolution is relatively low for reliable master plan analysis."
        )

    if quality.label == "Low":
        warnings.append(
            "Image quality is low and may reduce downstream confidence."
        )

    return ImageMetadata(
        image_path=str(source_path),
        normalized_image_path=str(normalized_path),
        file_name=source_path.name,
        file_extension=source_path.suffix.lower(),
        file_size_mb=file_size_mb,
        format=image_format,
        mode=image_mode,
        dimensions=dimensions,
        is_supported_format=True,
        is_within_size_limit=is_within_size_limit,
        quality=quality,
        processing_warnings=warnings,
    )


def assess_image_quality(
    image_path: str,
    dimensions: ImageDimensions,
    file_size_mb: float,
    is_within_size_limit: bool,
) -> ImageQualityAssessment:
    reasons: list[str] = []

    sharpness = calculate_laplacian_variance(image_path)
    brightness = calculate_brightness_score(image_path)
    colorfulness = calculate_colorfulness_score(image_path)

    score = 0.50

    if dimensions.width >= 1200 and dimensions.height >= 800:
        score += 0.15
        reasons.append("Image resolution is sufficient for master plan analysis.")
    elif dimensions.width >= 800 and dimensions.height >= 600:
        score += 0.08
        reasons.append("Image resolution is acceptable.")
    else:
        score -= 0.12
        reasons.append("Image resolution is low.")

    if sharpness >= 100:
        score += 0.12
        reasons.append("Image sharpness appears good.")
    elif sharpness >= 40:
        score += 0.04
        reasons.append("Image sharpness appears acceptable.")
    else:
        score -= 0.12
        reasons.append("Image appears blurry or low-detail.")

    if 70 <= brightness <= 220:
        score += 0.08
        reasons.append("Image brightness is within a usable range.")
    else:
        score -= 0.08
        reasons.append("Image brightness may be too low or too high.")

    if colorfulness >= 20:
        score += 0.07
        reasons.append("Image has enough color variation for visual class detection.")
    else:
        score -= 0.06
        reasons.append("Image has low color variation.")

    if is_within_size_limit:
        score += 0.03
        reasons.append("Image file size is within configured limit.")
    else:
        score -= 0.08
        reasons.append("Image file size exceeds configured limit.")

    score = max(0.0, min(1.0, round(score, 2)))

    if score >= 0.80:
        label = "High"
    elif score >= 0.55:
        label = "Medium"
    elif score >= 0.30:
        label = "Low"
    else:
        label = "Insufficient"

    reasons.append(f"Sharpness metric: {sharpness}")
    reasons.append(f"Brightness metric: {brightness}")
    reasons.append(f"Colorfulness metric: {colorfulness}")

    return ImageQualityAssessment(
        score=score,
        label=label,
        reasons=reasons,
    )
