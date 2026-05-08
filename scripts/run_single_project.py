import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

from app.config import get_settings
from app.services.image_preprocessor import preprocess_master_plan_image
from app.services.json_parser import parse_datacenter_json_file
from app.services.segmentation_engine import run_opencv_segmentation
from app.services.vision_analyzer import analyze_master_plan_with_openai
from app.utils.file_utils import write_json_file


console = Console()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Green Open Area Intelligence Engine for a single project."
    )
    parser.add_argument(
        "--json",
        required=True,
        help="Path to project Datacenter JSON file.",
    )
    parser.add_argument(
        "--image",
        required=False,
        help="Path to project master plan image.",
    )
    parser.add_argument(
        "--run-vision",
        action="store_true",
        help="Run OpenAI Vision analysis. Requires OPENAI_API_KEY in .env.",
    )
    parser.add_argument(
        "--run-segmentation",
        action="store_true",
        help="Run OpenCV segmentation on the normalized master plan image.",
    )

    args = parser.parse_args()
    settings = get_settings()

    parsed_metadata = parse_datacenter_json_file(args.json)

    project_metadata_output_path = (
        settings.data_output_json_dir
        / f"{parsed_metadata.project_id}_parsed_project_metadata.json"
    )

    write_json_file(
        project_metadata_output_path,
        parsed_metadata.model_dump(mode="json"),
    )

    project_table = Table(title="Parsed Project Metadata")
    project_table.add_column("Field", style="cyan")
    project_table.add_column("Value", style="green")

    project_table.add_row("Project ID", parsed_metadata.project_id)
    project_table.add_row("Project Name", parsed_metadata.project_name or "-")
    project_table.add_row("City", parsed_metadata.city or "-")
    project_table.add_row("Locality", parsed_metadata.locality or "-")
    project_table.add_row("Project Area Acres", str(parsed_metadata.project_area_acres or "-"))
    project_table.add_row("Total Units", str(parsed_metadata.total_units or "-"))
    project_table.add_row("Status", parsed_metadata.status or "-")
    project_table.add_row("Developer", parsed_metadata.developer_name or "-")
    project_table.add_row("Amenities Count", str(len(parsed_metadata.amenities)))
    project_table.add_row("Green Signals", ", ".join(parsed_metadata.green_amenity_signals) or "-")
    project_table.add_row("Open Space Signals", ", ".join(parsed_metadata.open_space_signals) or "-")
    project_table.add_row("RERA Records", str(len(parsed_metadata.rera_records)))
    project_table.add_row("Unit Variants", str(len(parsed_metadata.unit_mix)))
    project_table.add_row(
        "Master Plan Found",
        "Yes" if parsed_metadata.master_plan is not None else "No",
    )
    project_table.add_row("Project Metadata Output", str(project_metadata_output_path))

    console.print(project_table)

    image_metadata = None

    if args.image:
        image_metadata = preprocess_master_plan_image(args.image)

        image_metadata_output_path = (
            settings.data_output_json_dir / "master_plan_image_metadata.json"
        )

        write_json_file(
            image_metadata_output_path,
            image_metadata.model_dump(mode="json"),
        )

        image_table = Table(title="Master Plan Image Metadata")
        image_table.add_column("Field", style="cyan")
        image_table.add_column("Value", style="green")

        image_table.add_row("File Name", image_metadata.file_name)
        image_table.add_row("Extension", image_metadata.file_extension)
        image_table.add_row("Size MB", str(image_metadata.file_size_mb))
        image_table.add_row("Format", image_metadata.format or "-")
        image_table.add_row("Mode", image_metadata.mode or "-")
        image_table.add_row("Width", str(image_metadata.dimensions.width))
        image_table.add_row("Height", str(image_metadata.dimensions.height))
        image_table.add_row("Total Pixels", str(image_metadata.dimensions.total_pixels))
        image_table.add_row("Quality Score", str(image_metadata.quality.score))
        image_table.add_row("Quality Label", image_metadata.quality.label)
        image_table.add_row("Normalized Image", image_metadata.normalized_image_path or "-")
        image_table.add_row("Image Metadata Output", str(image_metadata_output_path))

        console.print(image_table)

        if image_metadata.processing_warnings:
            console.print("[yellow]Image Processing Warnings:[/yellow]")
            for warning in image_metadata.processing_warnings:
                console.print(f"- {warning}")

    if args.run_vision:
        if image_metadata is None:
            raise ValueError("--run-vision requires --image.")

        console.print("[cyan]Running OpenAI Vision analysis...[/cyan]")

        vision_result = analyze_master_plan_with_openai(
            project=parsed_metadata,
            image_metadata=image_metadata,
        )

        vision_output_path = (
            settings.data_output_json_dir
            / f"{parsed_metadata.project_id}_vision_analysis.json"
        )

        write_json_file(
            vision_output_path,
            vision_result.model_dump(mode="json"),
        )

        vision_table = Table(title="OpenAI Vision Analysis")
        vision_table.add_column("Field", style="cyan")
        vision_table.add_column("Value", style="green")

        vision_table.add_row("Boundary Visible", str(vision_result.boundary.boundary_visible))
        vision_table.add_row("Boundary Confidence", vision_result.boundary.boundary_confidence)
        vision_table.add_row(
            "Manual Correction Recommended",
            str(vision_result.boundary.manual_correction_recommended),
        )
        vision_table.add_row(
            "Green Area Visual Estimate",
            vision_result.green_area_visual_estimate.qualitative_estimate,
        )
        vision_table.add_row(
            "Open Area Visual Estimate",
            vision_result.open_area_visual_estimate.qualitative_estimate,
        )
        vision_table.add_row(
            "Building Footprint Visual Estimate",
            vision_result.building_footprint_visual_estimate.qualitative_estimate,
        )
        vision_table.add_row("Detected Components", str(len(vision_result.detected_components)))
        vision_table.add_row("Warnings", str(len(vision_result.warnings)))
        vision_table.add_row("Vision Output", str(vision_output_path))

        console.print(vision_table)

    if args.run_segmentation:
        if image_metadata is None:
            raise ValueError("--run-segmentation requires --image.")

        console.print("[cyan]Running OpenCV segmentation...[/cyan]")

        segmentation_result = run_opencv_segmentation(
            image_metadata=image_metadata,
            project_id=parsed_metadata.project_id,
        )

        segmentation_output_path = (
            settings.data_output_json_dir
            / f"{parsed_metadata.project_id}_segmentation_result.json"
        )

        write_json_file(
            segmentation_output_path,
            segmentation_result.model_dump(mode="json"),
        )

        segmentation_table = Table(title="OpenCV Segmentation Result")
        segmentation_table.add_column("Class", style="cyan")
        segmentation_table.add_column("Pixels", style="green")
        segmentation_table.add_column("Percentage", style="green")

        for item in segmentation_result.classes:
            segmentation_table.add_row(
                item.class_name,
                str(item.pixel_count),
                f"{item.percentage}%",
            )

        console.print(segmentation_table)
        console.print(f"[green]Segmentation output:[/green] {segmentation_output_path}")
        console.print(f"[green]Segmentation overlay:[/green] {segmentation_result.output_paths.overlay_path}")

        if segmentation_result.warnings:
            console.print("[yellow]Segmentation Warnings:[/yellow]")
            for warning in segmentation_result.warnings:
                console.print(f"- {warning}")


if __name__ == "__main__":
    main()
