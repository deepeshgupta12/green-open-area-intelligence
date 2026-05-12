from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.services.area_calculator import build_area_estimate
from app.services.category_insight_engine import build_category_comparison
from app.services.image_preprocessor import preprocess_master_plan_image
from app.services.frontend_contract_validator import finalize_frontend_comparison_contract
from app.services.json_parser import parse_datacenter_json_file
from app.services.master_plan_compare_engine import build_master_plan_comparison
from app.services.master_plan_comparison_report_writer import write_master_plan_comparison_outputs
from app.services.master_plan_narrative_engine import enhance_master_plan_comparison_with_gemini
from app.services.master_plan_understanding_engine import extract_master_plan_understanding
from app.services.report_writer import write_final_outputs
from app.services.segmentation_engine import run_opencv_segmentation
from app.services.vision_analyzer import analyze_master_plan_with_gemini
from app.utils.file_utils import ensure_directory, write_json_file


app = FastAPI(
    title="Green Open Area Intelligence Engine",
    description=(
        "Backend API for estimating Green Area and Open Area from "
        "project Datacenter JSON and master plan images."
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check() -> dict:
    settings = get_settings()

    return {
        "status": "ok",
        "app_name": settings.app_name,
        "app_env": settings.app_env,
        "default_port": 2345,
    }


@app.post("/estimate")
async def estimate_green_open_area(
    project_json_file: UploadFile = File(...),
    master_plan_image_file: UploadFile = File(...),
    run_vision: bool = Form(False),
    run_segmentation: bool = Form(True),
    run_area_estimate: bool = Form(False),
    run_category_comparison: bool = Form(False),
    write_report: bool = Form(False),
) -> dict:
    settings = get_settings()

    if run_area_estimate and not run_vision:
        raise HTTPException(
            status_code=400,
            detail="run_area_estimate=true requires run_vision=true.",
        )

    if run_area_estimate and not run_segmentation:
        raise HTTPException(
            status_code=400,
            detail="run_area_estimate=true requires run_segmentation=true.",
        )

    if run_category_comparison and not run_area_estimate:
        raise HTTPException(
            status_code=400,
            detail="run_category_comparison=true requires run_area_estimate=true.",
        )

    if write_report and not run_area_estimate:
        raise HTTPException(
            status_code=400,
            detail="write_report=true requires run_area_estimate=true.",
        )

    run_id = str(uuid4())

    run_input_dir = ensure_directory(settings.data_input_dir / "api_runs" / run_id)
    run_output_dir = ensure_directory(settings.data_output_dir / "api_runs" / run_id)
    run_json_dir = ensure_directory(run_output_dir / "json")
    run_reports_dir = ensure_directory(run_output_dir / "reports")
    run_overlays_dir = ensure_directory(run_output_dir / "overlays")

    project_json_path = run_input_dir / _safe_upload_name(
        project_json_file.filename or "project.json",
        fallback_extension=".json",
    )

    image_path = run_input_dir / _safe_upload_name(
        master_plan_image_file.filename or "master_plan.jpg",
        fallback_extension=".jpg",
    )

    await _save_upload_file(project_json_file, project_json_path)
    await _save_upload_file(master_plan_image_file, image_path)

    try:
        project = parse_datacenter_json_file(str(project_json_path))
        image_metadata = preprocess_master_plan_image(str(image_path))

        run_artifacts: dict[str, str | None] = {
            "input_project_json_path": str(project_json_path),
            "input_master_plan_image_path": str(image_path),
            "project_metadata_json_path": None,
            "image_metadata_json_path": None,
            "vision_analysis_json_path": None,
            "segmentation_result_json_path": None,
            "area_estimate_json_path": None,
            "category_comparison_json_path": None,
            "markdown_report_path": None,
            "compare_contract_path": None,
            "normalized_image_path": image_metadata.normalized_image_path,
            "segmentation_overlay_path": None,
        }

        project_metadata_output_path = run_json_dir / f"{project.project_id}_parsed_project_metadata.json"
        image_metadata_output_path = run_json_dir / "master_plan_image_metadata.json"

        write_json_file(project_metadata_output_path, project.model_dump(mode="json"))
        write_json_file(image_metadata_output_path, image_metadata.model_dump(mode="json"))

        run_artifacts["project_metadata_json_path"] = str(project_metadata_output_path)
        run_artifacts["image_metadata_json_path"] = str(image_metadata_output_path)

        response: dict = {
            "run_id": run_id,
            "run_artifacts": run_artifacts,
            "project_metadata": project.model_dump(mode="json"),
            "image_metadata": image_metadata.model_dump(mode="json"),
            "vision_analysis": None,
            "segmentation_result": None,
            "area_estimate": None,
            "category_comparison": None,
            "final_outputs": None,
        }

        vision_result = None
        segmentation_result = None
        area_estimate = None
        category_comparison = None

        if run_vision:
            vision_result = analyze_master_plan_with_gemini(
                project=project,
                image_metadata=image_metadata,
            )

            vision_output_path = run_json_dir / f"{project.project_id}_vision_analysis.json"
            write_json_file(vision_output_path, vision_result.model_dump(mode="json"))

            run_artifacts["vision_analysis_json_path"] = str(vision_output_path)
            response["vision_analysis"] = vision_result.model_dump(mode="json")

        if run_segmentation:
            segmentation_result = run_opencv_segmentation(
                image_metadata=image_metadata,
                project_id=project.project_id,
            )

            segmentation_output_path = run_json_dir / f"{project.project_id}_segmentation_result.json"
            write_json_file(segmentation_output_path, segmentation_result.model_dump(mode="json"))

            run_artifacts["segmentation_result_json_path"] = str(segmentation_output_path)
            run_artifacts["segmentation_overlay_path"] = segmentation_result.output_paths.overlay_path
            response["segmentation_result"] = segmentation_result.model_dump(mode="json")

        if run_area_estimate:
            if vision_result is None or segmentation_result is None:
                raise HTTPException(
                    status_code=400,
                    detail="run_area_estimate requires both vision and segmentation results.",
                )

            area_estimate = build_area_estimate(
                project=project,
                image_metadata=image_metadata,
                vision=vision_result,
                segmentation=segmentation_result,
            )

            area_estimate_output_path = run_json_dir / f"{project.project_id}_area_estimate.json"
            write_json_file(area_estimate_output_path, area_estimate.model_dump(mode="json"))

            run_artifacts["area_estimate_json_path"] = str(area_estimate_output_path)
            response["area_estimate"] = area_estimate.model_dump(mode="json")

        if run_category_comparison:
            if vision_result is None or segmentation_result is None or area_estimate is None:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "run_category_comparison=true requires run_vision=true, "
                        "run_segmentation=true, and run_area_estimate=true."
                    ),
                )

            category_comparison = build_category_comparison(
                project=project,
                image_metadata=image_metadata,
                vision=vision_result,
                segmentation=segmentation_result,
                area_estimate=area_estimate,
            )

            category_comparison_output_path = (
                run_json_dir / f"{project.project_id}_category_comparison.json"
            )

            write_json_file(
                category_comparison_output_path,
                category_comparison.model_dump(mode="json"),
            )

            run_artifacts["category_comparison_json_path"] = str(category_comparison_output_path)
            response["category_comparison"] = category_comparison.model_dump(mode="json")

        if write_report:
            if vision_result is None or segmentation_result is None or area_estimate is None:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "write_report=true requires run_vision=true, "
                        "run_segmentation=true, and run_area_estimate=true."
                    ),
                )

            final_outputs = write_final_outputs(
                project=project,
                image_metadata=image_metadata,
                vision=vision_result,
                segmentation=segmentation_result,
                area_estimate=area_estimate,
                category_comparison=category_comparison,
                reports_dir=run_reports_dir,
                json_dir=run_json_dir,
            )

            run_artifacts["markdown_report_path"] = final_outputs["markdown_report_path"]
            run_artifacts["compare_contract_path"] = final_outputs["compare_contract_path"]
            if final_outputs.get("category_comparison_path"):
                run_artifacts["category_comparison_json_path"] = final_outputs["category_comparison_path"]
            response["final_outputs"] = final_outputs

        run_summary_path = run_json_dir / "run_summary.json"
        write_json_file(
            run_summary_path,
            {
                "run_id": run_id,
                "project_id": project.project_id,
                "project_name": project.project_name,
                "run_options": {
                    "run_vision": run_vision,
                    "run_segmentation": run_segmentation,
                    "run_area_estimate": run_area_estimate,
                    "run_category_comparison": run_category_comparison,
                    "write_report": write_report,
                },
                "run_artifacts": run_artifacts,
            },
        )

        run_artifacts["run_summary_json_path"] = str(run_summary_path)

        return response

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


async def _save_upload_file(upload_file: UploadFile, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)

    content = await upload_file.read()

    if not content:
        raise HTTPException(
            status_code=400,
            detail=f"Uploaded file is empty: {upload_file.filename}",
        )

    destination.write_bytes(content)


def _safe_upload_name(file_name: str, fallback_extension: str) -> str:
    raw_name = Path(file_name).name

    if "." not in raw_name:
        raw_name = f"{raw_name}{fallback_extension}"

    return raw_name


@app.post("/compare-master-plans")
async def compare_master_plans(
    project_a_json_file: UploadFile = File(...),
    project_a_master_plan_image_file: UploadFile = File(...),
    project_b_json_file: UploadFile = File(...),
    project_b_master_plan_image_file: UploadFile = File(...),
    project_c_json_file: UploadFile = File(...),
    project_c_master_plan_image_file: UploadFile = File(...),
    run_vision: bool = Form(True),
    run_segmentation: bool = Form(True),
    run_area_estimate: bool = Form(True),
    run_category_comparison: bool = Form(True),
    write_report: bool = Form(True),
    use_ai_narrative: bool = Form(True),
    use_ai_structure_extraction: bool = Form(True),
) -> dict:
    settings = get_settings()

    if not run_vision or not run_segmentation or not run_area_estimate or not run_category_comparison:
        raise HTTPException(
            status_code=400,
            detail=(
                "compare-master-plans currently requires run_vision=true, "
                "run_segmentation=true, run_area_estimate=true, and run_category_comparison=true."
            ),
        )

    comparison_run_id = str(uuid4())

    compare_input_dir = ensure_directory(settings.data_input_dir / "compare_runs" / comparison_run_id)
    compare_output_dir = ensure_directory(settings.data_output_dir / "compare_runs" / comparison_run_id)
    compare_json_dir = ensure_directory(compare_output_dir / "json")

    try:
        bundle_a = await _process_compare_project_bundle(
            slot="A",
            project_json_file=project_a_json_file,
            master_plan_image_file=project_a_master_plan_image_file,
            input_dir=compare_input_dir,
            output_json_dir=compare_json_dir,
            use_ai_structure_extraction=use_ai_structure_extraction,
        )
        bundle_b = await _process_compare_project_bundle(
            slot="B",
            project_json_file=project_b_json_file,
            master_plan_image_file=project_b_master_plan_image_file,
            input_dir=compare_input_dir,
            output_json_dir=compare_json_dir,
            use_ai_structure_extraction=use_ai_structure_extraction,
        )
        bundle_c = await _process_compare_project_bundle(
            slot="C",
            project_json_file=project_c_json_file,
            master_plan_image_file=project_c_master_plan_image_file,
            input_dir=compare_input_dir,
            output_json_dir=compare_json_dir,
            use_ai_structure_extraction=use_ai_structure_extraction,
        )

        comparison = build_master_plan_comparison(
            project_a=bundle_a["project"],
            area_a=bundle_a["area_estimate"],
            category_a=bundle_a["category_comparison"],
            project_b=bundle_b["project"],
            area_b=bundle_b["area_estimate"],
            category_b=bundle_b["category_comparison"],
            project_c=bundle_c["project"],
            area_c=bundle_c["area_estimate"],
            category_c=bundle_c["category_comparison"],
            comparison_run_id=comparison_run_id,
            understanding_a=bundle_a["master_plan_understanding"],
            understanding_b=bundle_b["master_plan_understanding"],
            understanding_c=bundle_c["master_plan_understanding"],
        )

        if use_ai_narrative:
            comparison = enhance_master_plan_comparison_with_gemini(comparison)

        comparison = finalize_frontend_comparison_contract(comparison)

        final_outputs = None
        if write_report:
            final_outputs = write_master_plan_comparison_outputs(
                comparison=comparison,
                output_dir=compare_output_dir,
            )

        return {
            "comparison_run_id": comparison_run_id,
            "projects": comparison.projects,
            "category_comparison_matrix": comparison.category_comparison_matrix,
            "category_winners": comparison.category_winners,
            "overall_recommendation": comparison.overall_recommendation,
            "user_friendly_summary": comparison.user_friendly_summary,
            "internal_evidence_quality": comparison.internal_evidence_quality,
            "run_artifacts": {
                "compare_input_dir": str(compare_input_dir),
                "compare_output_dir": str(compare_output_dir),
                "comparison_json_path": final_outputs["comparison_json_path"] if final_outputs else None,
                "comparison_report_path": final_outputs["comparison_report_path"] if final_outputs else None,
                "project_a_artifacts": bundle_a["artifacts"],
                "project_b_artifacts": bundle_b["artifacts"],
                "project_c_artifacts": bundle_c["artifacts"],
            },
            "notes": comparison.notes,
        }

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


async def _process_compare_project_bundle(
    slot: str,
    project_json_file: UploadFile,
    master_plan_image_file: UploadFile,
    input_dir: Path,
    output_json_dir: Path,
    use_ai_structure_extraction: bool = True,
) -> dict:
    project_json_path = input_dir / f"project_{slot.lower()}_{_safe_upload_name(project_json_file.filename or 'project.json', '.json')}"
    image_path = input_dir / f"project_{slot.lower()}_{_safe_upload_name(master_plan_image_file.filename or 'master_plan.jpg', '.jpg')}"

    await _save_upload_file(project_json_file, project_json_path)
    await _save_upload_file(master_plan_image_file, image_path)

    project = parse_datacenter_json_file(str(project_json_path))
    image_metadata = preprocess_master_plan_image(str(image_path))

    vision = analyze_master_plan_with_gemini(project=project, image_metadata=image_metadata)
    segmentation = run_opencv_segmentation(image_metadata=image_metadata, project_id=project.project_id)
    area_estimate = build_area_estimate(
        project=project,
        image_metadata=image_metadata,
        vision=vision,
        segmentation=segmentation,
    )
    category_comparison = build_category_comparison(
        project=project,
        image_metadata=image_metadata,
        vision=vision,
        segmentation=segmentation,
        area_estimate=area_estimate,
    )

    master_plan_understanding = extract_master_plan_understanding(
        project=project,
        image_metadata=image_metadata,
        vision=vision,
        output_dir=output_json_dir.parent / "overlays",
        use_gemini=use_ai_structure_extraction,
    )

    project_prefix = f"project_{slot.lower()}_{project.project_id}"

    project_metadata_path = output_json_dir / f"{project_prefix}_parsed_project_metadata.json"
    image_metadata_path = output_json_dir / f"{project_prefix}_image_metadata.json"
    vision_path = output_json_dir / f"{project_prefix}_vision_analysis.json"
    segmentation_path = output_json_dir / f"{project_prefix}_segmentation_result.json"
    area_path = output_json_dir / f"{project_prefix}_area_estimate.json"
    category_path = output_json_dir / f"{project_prefix}_category_comparison.json"
    understanding_path = output_json_dir / f"{project_prefix}_master_plan_understanding.json"

    write_json_file(project_metadata_path, project.model_dump(mode="json"))
    write_json_file(image_metadata_path, image_metadata.model_dump(mode="json"))
    write_json_file(vision_path, vision.model_dump(mode="json"))
    write_json_file(segmentation_path, segmentation.model_dump(mode="json"))
    write_json_file(area_path, area_estimate.model_dump(mode="json"))
    write_json_file(category_path, category_comparison.model_dump(mode="json"))
    write_json_file(understanding_path, master_plan_understanding.model_dump(mode="json"))

    return {
        "project": project,
        "image_metadata": image_metadata,
        "vision": vision,
        "segmentation": segmentation,
        "area_estimate": area_estimate,
        "category_comparison": category_comparison,
        "master_plan_understanding": master_plan_understanding,
        "artifacts": {
            "input_project_json_path": str(project_json_path),
            "input_master_plan_image_path": str(image_path),
            "project_metadata_json_path": str(project_metadata_path),
            "image_metadata_json_path": str(image_metadata_path),
            "vision_analysis_json_path": str(vision_path),
            "segmentation_result_json_path": str(segmentation_path),
            "area_estimate_json_path": str(area_path),
            "category_comparison_json_path": str(category_path),
            "master_plan_understanding_json_path": str(understanding_path),
        },
    }
