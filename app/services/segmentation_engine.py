from pathlib import Path

import cv2
import numpy as np

from app.config import get_settings
from app.rules.class_definitions import (
    BUILT_STRUCTURE,
    GREEN_LANDSCAPE,
    PAVED_OPEN_AREA,
    SEGMENTATION_CLASS_DESCRIPTIONS,
    UNKNOWN_UNCLASSIFIED,
    WATER_POOL,
)
from app.schemas.image_schema import ImageMetadata
from app.schemas.segmentation_schema import (
    SegmentationClassResult,
    SegmentationOutputPaths,
    SegmentationResult,
)


def run_opencv_segmentation(
    image_metadata: ImageMetadata,
    project_id: str,
) -> SegmentationResult:
    if not image_metadata.normalized_image_path:
        raise ValueError("Normalized image path is missing. Run image preprocessing first.")

    settings = get_settings()

    image_path = Path(image_metadata.normalized_image_path)

    image_bgr = cv2.imread(str(image_path), cv2.IMREAD_COLOR)

    if image_bgr is None:
        raise ValueError(f"Unable to read normalized image with OpenCV: {image_path}")

    height, width = image_bgr.shape[:2]
    total_pixels = int(width * height)

    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)

    green_mask = _create_green_mask(hsv)
    water_mask = _create_water_mask(hsv)
    built_mask = _create_built_mask(image_bgr, hsv)
    paved_mask = _create_paved_mask(image_bgr, hsv)

    green_mask, water_mask, built_mask, paved_mask = _remove_mask_overlaps(
        green_mask=green_mask,
        water_mask=water_mask,
        built_mask=built_mask,
        paved_mask=paved_mask,
    )

    known_mask = cv2.bitwise_or(green_mask, water_mask)
    known_mask = cv2.bitwise_or(known_mask, built_mask)
    known_mask = cv2.bitwise_or(known_mask, paved_mask)
    unknown_mask = cv2.bitwise_not(known_mask)

    green_count = _count_mask_pixels(green_mask)
    water_count = _count_mask_pixels(water_mask)
    built_count = _count_mask_pixels(built_mask)
    paved_count = _count_mask_pixels(paved_mask)
    unknown_count = _count_mask_pixels(unknown_mask)

    output_base = settings.data_output_overlays_dir
    green_mask_path = output_base / "master_plan_green_mask.png"
    water_mask_path = output_base / "master_plan_water_mask.png"
    built_mask_path = output_base / "master_plan_built_mask.png"
    paved_mask_path = output_base / "master_plan_paved_mask.png"
    overlay_path = output_base / "master_plan_segmentation_overlay.png"

    _write_mask(green_mask_path, green_mask)
    _write_mask(water_mask_path, water_mask)
    _write_mask(built_mask_path, built_mask)
    _write_mask(paved_mask_path, paved_mask)

    overlay = _create_overlay(
        image_bgr=image_bgr,
        green_mask=green_mask,
        water_mask=water_mask,
        built_mask=built_mask,
        paved_mask=paved_mask,
    )
    cv2.imwrite(str(overlay_path), overlay)

    classes = [
        _class_result(GREEN_LANDSCAPE, green_count, total_pixels),
        _class_result(WATER_POOL, water_count, total_pixels),
        _class_result(BUILT_STRUCTURE, built_count, total_pixels),
        _class_result(PAVED_OPEN_AREA, paved_count, total_pixels),
        _class_result(UNKNOWN_UNCLASSIFIED, unknown_count, total_pixels),
    ]

    warnings: list[str] = []
    notes: list[str] = [
        "OpenCV segmentation is heuristic and color/contrast based.",
        "This step does not produce final green/open area estimates.",
        "Final estimates will combine vision model, segmentation, guardrails, and confidence logic.",
    ]

    unknown_percentage = _percentage(unknown_count, total_pixels)
    if unknown_percentage > 40:
        warnings.append(
            "Unknown/unclassified area is high. Manual review or improved segmentation may be needed."
        )

    if _percentage(green_count, total_pixels) == 0:
        warnings.append("No green pixels were detected by the heuristic segmentation.")

    return SegmentationResult(
        image_path=str(image_path),
        image_width=width,
        image_height=height,
        total_pixels=total_pixels,
        classes=classes,
        output_paths=SegmentationOutputPaths(
            overlay_path=str(overlay_path),
            green_mask_path=str(green_mask_path),
            water_mask_path=str(water_mask_path),
            built_mask_path=str(built_mask_path),
            paved_mask_path=str(paved_mask_path),
        ),
        warnings=warnings,
        notes=notes,
    )


def _create_green_mask(hsv: np.ndarray) -> np.ndarray:
    lower_green = np.array([30, 25, 40])
    upper_green = np.array([95, 255, 255])

    mask = cv2.inRange(hsv, lower_green, upper_green)
    return _clean_mask(mask)


def _create_water_mask(hsv: np.ndarray) -> np.ndarray:
    lower_blue = np.array([85, 25, 40])
    upper_blue = np.array([135, 255, 255])

    mask = cv2.inRange(hsv, lower_blue, upper_blue)
    return _clean_mask(mask)


def _create_built_mask(image_bgr: np.ndarray, hsv: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)

    # Built structures in master plans often appear as dark grey, black outlines,
    # brown blocks, or high-contrast geometric shapes.
    dark_mask = cv2.inRange(gray, 0, 95)

    lower_brown = np.array([5, 25, 35])
    upper_brown = np.array([30, 180, 210])
    brown_mask = cv2.inRange(hsv, lower_brown, upper_brown)

    mask = cv2.bitwise_or(dark_mask, brown_mask)
    return _clean_mask(mask)


def _create_paved_mask(image_bgr: np.ndarray, hsv: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)

    # Paved/open hardscape tends to appear as light grey, beige, white-ish,
    # or low saturation areas.
    low_saturation = cv2.inRange(hsv[:, :, 1], 0, 70)
    medium_brightness = cv2.inRange(gray, 90, 245)

    mask = cv2.bitwise_and(low_saturation, medium_brightness)

    lower_beige = np.array([10, 10, 80])
    upper_beige = np.array([35, 100, 255])
    beige_mask = cv2.inRange(hsv, lower_beige, upper_beige)

    mask = cv2.bitwise_or(mask, beige_mask)
    return _clean_mask(mask)


def _clean_mask(mask: np.ndarray) -> np.ndarray:
    kernel = np.ones((5, 5), np.uint8)

    cleaned = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_CLOSE, kernel)

    return cleaned


def _remove_mask_overlaps(
    green_mask: np.ndarray,
    water_mask: np.ndarray,
    built_mask: np.ndarray,
    paved_mask: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    # Priority:
    # 1. green
    # 2. water
    # 3. built
    # 4. paved
    not_green = cv2.bitwise_not(green_mask)

    water_mask = cv2.bitwise_and(water_mask, not_green)

    occupied = cv2.bitwise_or(green_mask, water_mask)
    not_occupied = cv2.bitwise_not(occupied)

    built_mask = cv2.bitwise_and(built_mask, not_occupied)

    occupied = cv2.bitwise_or(occupied, built_mask)
    not_occupied = cv2.bitwise_not(occupied)

    paved_mask = cv2.bitwise_and(paved_mask, not_occupied)

    return green_mask, water_mask, built_mask, paved_mask


def _count_mask_pixels(mask: np.ndarray) -> int:
    return int(cv2.countNonZero(mask))


def _percentage(pixel_count: int, total_pixels: int) -> float:
    if total_pixels <= 0:
        return 0.0

    return round((pixel_count / total_pixels) * 100, 2)


def _class_result(
    class_name: str,
    pixel_count: int,
    total_pixels: int,
) -> SegmentationClassResult:
    return SegmentationClassResult(
        class_name=class_name,
        pixel_count=pixel_count,
        percentage=_percentage(pixel_count, total_pixels),
        description=SEGMENTATION_CLASS_DESCRIPTIONS[class_name],
    )


def _write_mask(path: Path, mask: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), mask)


def _create_overlay(
    image_bgr: np.ndarray,
    green_mask: np.ndarray,
    water_mask: np.ndarray,
    built_mask: np.ndarray,
    paved_mask: np.ndarray,
) -> np.ndarray:
    overlay = image_bgr.copy()

    color_layer = np.zeros_like(image_bgr)

    # BGR colors
    color_layer[green_mask > 0] = (0, 180, 0)
    color_layer[water_mask > 0] = (220, 120, 0)
    color_layer[built_mask > 0] = (40, 40, 220)
    color_layer[paved_mask > 0] = (180, 180, 180)

    blended = cv2.addWeighted(overlay, 0.65, color_layer, 0.35, 0)

    return blended
