import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

from app.config import get_settings
from app.services.json_parser import parse_datacenter_json_file
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
        help="Path to project master plan image. Image processing starts from Step 3.",
    )

    args = parser.parse_args()
    settings = get_settings()

    parsed_metadata = parse_datacenter_json_file(args.json)

    output_path = (
        settings.data_output_json_dir
        / f"{parsed_metadata.project_id}_parsed_project_metadata.json"
    )

    write_json_file(output_path, parsed_metadata.model_dump(mode="json"))

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
    table.add_row(
        "Master Plan Found",
        "Yes" if parsed_metadata.master_plan is not None else "No",
    )
    table.add_row("Output", str(output_path))

    console.print(table)

    if args.image:
        console.print(
            "[yellow]Image path accepted but image processing starts from Step 3.[/yellow]"
        )


if __name__ == "__main__":
    main()
