from pydantic import BaseModel, Field


class ImageDimensions(BaseModel):
    width: int
    height: int
    total_pixels: int


class ImageQualityAssessment(BaseModel):
    score: float
    label: str
    reasons: list[str] = Field(default_factory=list)


class ImageMetadata(BaseModel):
    image_path: str
    normalized_image_path: str | None = None

    file_name: str
    file_extension: str
    file_size_mb: float

    format: str | None = None
    mode: str | None = None
    dimensions: ImageDimensions

    is_supported_format: bool
    is_within_size_limit: bool

    quality: ImageQualityAssessment

    processing_warnings: list[str] = Field(default_factory=list)
