import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

from app.config import get_settings
from app.services.area_calculator import build_area_estimate
from app.services.category_insight_engine import build_category_comparison
from app.services.image_preprocessor import preprocess_master_plan_image
from app.services.json_parser import parse_datacenter_json_file
from app.services.report_writer import write_final_outputs
from app.services.segmentation_engine import run_opencv_segmentation
from app.services.vision_analyzer import analyze_master_plan_with_openai
from app.utils.file_utils import write_json_file


console = Console()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Green Open Area Intelligence Engine for a single project."
    )
    parser.add_argument("--json", required=True, help="Path to project Datacenter JSON file.")
    parser.add_argument("--image", required=False, help="Path to project master plan image.")
    parser.add_argument("--run-vision", action="store_true", help="Run OpenAI Vision analysis.")
    parser.add_argument("--run-segmentation", action="store_true", help="Run OpenCV segmentation.")
    parser.add_argument("--run-area-estimate", action="store_true", help="Build final area estimate.")
    parser.add_argument("--run-category-comparison", action="store_true", help="Build master plan category insights.")
    parser.add_argument("--write-report", action="store_true", help="Write final Markdown report and compare contract.")

    args = parser.parse_args()
    settings = get_settings()

    parsed_metadata = parse_datacenter_json_file(args.json)

    project_metadata_output_path = (
        settings.data_output_json_dir
        / f"{parsed_metadata.project_id}_parsed_project_metadata.json"
    )

    write_json_file(project_metadata_output_path, parsed_metadata.model_dump(mode="json"))
    _print_project_table(parsed_metadata, project_metadata_output_path)

    image_metadata = None
    vision_result = None
    segmentation_result = None
    area_estimate = None
    category_comparison = None

    if args.image:
        image_metadata = preprocess_master_plan_image(args.image)
        image_metadata_output_path = settings.data_output_json_dir / "master_plan_image_metadata.json"
        write_json_file(image_metadata_output_path, image_metadata.model_dump(mode="json"))
        _print_image_table(image_metadata, image_metadata_output_path)

    if args.run_vision:
        if image_metadata is None:
            raise ValueError("--run-vision requires --image.")

        console.print("[cyan]Running OpenAI Vision analysis...[/cyan]")

        vision_result = analyze_master_plan_with_openai(
            project=parsed_metadata,
            image_metadata=image_metadata,
        )

        vision_output_path = settings.data_output_json_dir / f"{parsed_metadata.project_id}_vision_analysis.json"
        write_json_file(vision_output_path, vision_result.model_dump(mode="json"))
        _print_vision_table(vision_result, vision_output_path)

    if args.run_segmentation:
        if image_metadata is None:
            raise ValueError("--run-segmentation requires --image.")

        console.print("[cyan]Running OpenCV segmentation...[/cyan]")

        segmentation_result = run_opencv_segmentation(
            image_metadata=image_metadata,
            project_id=parsed_metadata.project_id,
        )

        segmentation_output_path = settings.data_output_json_dir / f"{parsed_metadata.project_id}_segmentation_result.json"
        write_json_file(segmentation_output_path, segmentation_result.model_dump(mode="json"))
        _print_segmentation_table(segmentation_result, segmentation_output_path)

    if args.run_area_estimate:
        if image_metadata is None:
            raise ValueError("--run-area-estimate requires --image.")
        if vision_result is None:
            raise ValueError("--run-area-estimate requires --run-vision in this step.")
        if segmentation_result is None:
            raise ValueError("--run-area-estimate requires --run-segmentation in this step.")

        console.print("[cyan]Building final area estimate...[/cyan]")

        area_estimate = build_area_estimate(
            project=parsed_metadata,
            image_metadata=image_metadata,
            vision=vision_result,
            segmentation=segmentation_result,
        )

        area_estimate_output_path = settings.data_output_json_dir / f"{parsed_metadata.project_id}_area_estimate.json"
        write_json_file(area_estimate_output_path, area_estimate.model_dump(mode="json"))
        _print_area_estimate_table(area_estimate, area_estimate_output_path)

    if args.run_category_comparison:
        if image_metadata is None or vision_result is None or segmentation_result is None or area_estimate is None:
            raise ValueError(
                "--run-category-comparison requires --image, --run-vision, --run-segmentation, and --run-area-estimate."
            )

        console.print("[cyan]Building master plan category insights...[/cyan]")

        category_comparison = build_category_comparison(
            project=parsed_metadata,
            image_metadata=image_metadata,
            vision=vision_result,
            segmentation=segmentation_result,
            area_estimate=area_estimate,
        )

        category_output_path = settings.data_output_json_dir / f"{parsed_metadata.project_id}_category_comparison.json"
        write_json_file(category_output_path, category_comparison.model_dump(mode="json"))
        _print_category_comparison_table(category_comparison, category_output_path)

    if args.write_report:
        if image_metadata is None or vision_result is None or segmentation_result is None or area_estimate is None:
            raise ValueError(
                "--write-report requires --image, --run-vision, --run-segmentation, and --run-area-estimate."
            )

        console.print("[cyan]Writing final report and compare contract...[/cyan]")

        output_paths = write_final_outputs(
            project=parsed_metadata,
            image_metadata=image_metadata,
            vision=vision_result,
            segmentation=segmentation_result,
            area_estimate=area_estimate,
            category_comparison=category_comparison,
        )

        report_table = Table(title="Final Output Files")
        report_table.add_column("Output", style="cyan")
        report_table.add_column("Path", style="green")
        report_table.add_row("Markdown Report", output_paths["markdown_report_path"] or "-")
        report_table.add_row("Compare Contract", output_paths["compare_contract_path"] or "-")
        report_table.add_row("Category Comparison", output_paths["category_comparison_path"] or "-")
        console.print(report_table)


def _print_project_table(parsed_metadata, output_path: Path) -> None:
    table = Table(title="Parsed Project Metadata")
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Project ID", parsed_metadata.project_id)
    table.add_row("Project Name", parsed_metadata.project_name or "-")
    table.add_row("City", parsed_metadata.city or "-")
    table.add_row("Locality", parsed_metadata.locality or "-")
    table.add_row("Project Area Acres", str(parsed_metadata.project_area_acres or "-"))
    table.add_row("Total Units", str(parsed_metadata.total_units or "-"))
    table.add_row("Status", parsed_metadata.status or "-")
    table.add_row("Developer", parsed_metadata.developer_name or "-")
    table.add_row("Amenities Count", str(len(parsed_metadata.amenities)))
    table.add_row("Green Signals", ", ".join(parsed_metadata.green_amenity_signals) or "-")
    table.add_row("Open Space Signals", ", ".join(parsed_metadata.open_space_signals) or "-")
    table.add_row("RERA Records", str(len(parsed_metadata.rera_records)))
    table.add_row("Unit Variants", str(len(parsed_metadata.unit_mix)))
    table.add_row("Master Plan Found", "Yes" if parsed_metadata.master_plan is not None else "No")
    table.add_row("Project Metadata Output", str(output_path))
    console.print(table)


def _print_image_table(image_metadata, output_path: Path) -> None:
    table = Table(title="Master Plan Image Metadata")
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("File Name", image_metadata.file_name)
    table.add_row("Extension", image_metadata.file_extension)
    table.add_row("Size MB", str(image_metadata.file_size_mb))
    table.add_row("Format", image_metadata.format or "-")
    table.add_row("Mode", image_metadata.mode or "-")
    table.add_row("Width", str(image_metadata.dimensions.width))
    table.add_row("Height", str(image_metadata.dimensions.height))
    table.add_row("Total Pixels", str(image_metadata.dimensions.total_pixels))
    table.add_row("Quality Score", str(image_metadata.quality.score))
    table.add_row("Quality Label", image_metadata.quality.label)
    table.add_row("Normalized Image", image_metadata.normalized_image_path or "-")
    table.add_row("Image Metadata Output", str(output_path))
    console.print(table)


def _print_vision_table(vision_result, output_path: Path) -> None:
    table = Table(title="OpenAI Vision Analysis")
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Boundary Visible", str(vision_result.boundary.boundary_visible))
    table.add_row("Boundary Confidence", vision_result.boundary.boundary_confidence)
    table.add_row("Manual Correction Recommended", str(vision_result.boundary.manual_correction_recommended))
    table.add_row("Green Area Visual Estimate", vision_result.green_area_visual_estimate.qualitative_estimate)
    table.add_row("Open Area Visual Estimate", vision_result.open_area_visual_estimate.qualitative_estimate)
    table.add_row("Building Footprint Visual Estimate", vision_result.building_footprint_visual_estimate.qualitative_estimate)
    table.add_row("Detected Components", str(len(vision_result.detected_components)))
    table.add_row("Warnings", str(len(vision_result.warnings)))
    table.add_row("Vision Output", str(output_path))
    console.print(table)


def _print_segmentation_table(segmentation_result, output_path: Path) -> None:
    table = Table(title="OpenCV Segmentation Result")
    table.add_column("Class", style="cyan")
    table.add_column("Pixels", style="green")
    table.add_column("Percentage", style="green")

    for item in segmentation_result.classes:
        table.add_row(item.class_name, str(item.pixel_count), f"{item.percentage}%")

    console.print(table)
    console.print(f"[green]Segmentation output:[/green] {output_path}")
    console.print(f"[green]Segmentation overlay:[/green] {segmentation_result.output_paths.overlay_path}")


def _print_area_estimate_table(area_estimate, output_path: Path) -> None:
    table = Table(title="Final Area Estimate")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Estimated Green Area", area_estimate.green_area_percentage.display)
    table.add_row("Estimated Open Area", area_estimate.open_area_percentage.display)
    table.add_row("Confidence Score", str(area_estimate.confidence.score))
    table.add_row("Confidence Label", area_estimate.confidence.label)
    table.add_row("Guardrails Passed", str(area_estimate.guardrails.passed))
    table.add_row("Warnings", str(len(area_estimate.warnings)))
    table.add_row("Area Estimate Output", str(output_path))
    console.print(table)


def _print_category_comparison_table(category_comparison, output_path: Path) -> None:
    table = Table(title="Master Plan Category Insights")
    table.add_column("Category", style="cyan")
    table.add_column("Score", style="green")
    table.add_column("Rating", style="green")
    table.add_column("Confidence", style="green")
    table.add_column("One-Liner", style="white")

    for item in category_comparison.category_scores:
        table.add_row(
            item.category_label,
            str(item.score),
            item.rating,
            item.confidence_label,
            item.one_liner,
        )

    console.print(table)
    console.print(f"[green]Category comparison output:[/green] {output_path}")


if __name__ == "__main__":
    main()
