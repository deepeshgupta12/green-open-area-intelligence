from pydantic import BaseModel, Field


class SegmentationClassResult(BaseModel):
    class_name: str
    pixel_count: int
    percentage: float
    description: str


class SegmentationOutputPaths(BaseModel):
    overlay_path: str
    green_mask_path: str
    water_mask_path: str
    built_mask_path: str
    paved_mask_path: str


class SegmentationResult(BaseModel):
    image_path: str
    image_width: int
    image_height: int
    total_pixels: int

    classes: list[SegmentationClassResult] = Field(default_factory=list)

    output_paths: SegmentationOutputPaths

    warnings: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
