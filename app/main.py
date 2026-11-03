import logging
import re
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.config import get_settings
from app.services.area_calculator import build_area_estimate
from app.services.category_insight_engine import build_category_comparison
from app.services.image_preprocessor import preprocess_master_plan_image
from app.services.frontend_contract_validator import finalize_frontend_comparison_contract
from app.services.json_parser import parse_datacenter_json_file
from app.services.master_plan_compare_engine import build_master_plan_comparison
from app.services.master_plan_comparison_report_writer import write_master_plan_comparison_outputs
from app.agents.orchestrator import run_qa_loop
from app.schemas.analysis_response_schema import MasterPlanAnalysisResponse, MasterPlanEntitiesResponse, RunArtifacts
from app.schemas.area_schema import AreaEstimateResult
from app.schemas.master_plan_entity_schema import Diagnostic
from app.schemas.project_schema import ParsedProjectMetadata
from app.schemas.site_metrics_schema import SiteRecords
from app.services.density_benchmarks import load_density_benchmarks
from app.services.master_plan_entity_extractor import extract_master_plan_entities
from app.services.master_plan_narrative_engine import enhance_master_plan_comparison_with_gemini
from app.services.site_metrics_engine import area_inputs_from_estimate, build_site_metrics
from app.services.master_plan_understanding_engine import extract_master_plan_understanding
from app.services.report_writer import write_final_outputs
from app.services.segmentation_engine import run_opencv_segmentation
from app.services.vision_analyzer import analyze_master_plan_with_gemini
from app.utils.file_utils import ensure_directory, write_json_file
from app.utils.remote_image import IMAGE_EXTENSIONS, RemoteImageError, download_image


logger = logging.getLogger(__name__)

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
    use_ai_entity_extraction: bool = Form(False),
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
            use_ai_entity_extraction=use_ai_entity_extraction,
        )
        bundle_b = await _process_compare_project_bundle(
            slot="B",
            project_json_file=project_b_json_file,
            master_plan_image_file=project_b_master_plan_image_file,
            input_dir=compare_input_dir,
            output_json_dir=compare_json_dir,
            use_ai_structure_extraction=use_ai_structure_extraction,
            use_ai_entity_extraction=use_ai_entity_extraction,
        )
        bundle_c = await _process_compare_project_bundle(
            slot="C",
            project_json_file=project_c_json_file,
            master_plan_image_file=project_c_master_plan_image_file,
            input_dir=compare_input_dir,
            output_json_dir=compare_json_dir,
            use_ai_structure_extraction=use_ai_structure_extraction,
            use_ai_entity_extraction=use_ai_entity_extraction,
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
            "project_entity_maps": {
                "A": bundle_a["entity_map"],
                "B": bundle_b["entity_map"],
                "C": bundle_c["entity_map"],
            },
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
    use_ai_entity_extraction: bool = False,
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

    # Spatial entity map is optional: it adds a Gemini call per project, and a
    # failure here must not sink the whole comparison.
    entity_map = None
    entity_map_path = None
    if use_ai_entity_extraction:
        try:
            entity_map = extract_master_plan_entities(image_metadata=image_metadata, project=project)
            entity_map_path = output_json_dir / f"{project_prefix}_master_plan_entity_map.json"
            write_json_file(entity_map_path, entity_map.model_dump(mode="json"))
        except Exception as exc:  # noqa: BLE001
            master_plan_understanding.technical_warnings.append(
                f"Master-plan entity extraction failed for project {slot}: {exc}"
            )

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
        "entity_map": entity_map.model_dump(mode="json") if entity_map else None,
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
            "master_plan_entity_map_json_path": str(entity_map_path) if entity_map_path else None,
        },
    }


LINE_DRAWING_REASON = (
    "The drawing is an architectural block plan (line drawing, no legend): pixel colour carries little "
    "land-use signal, so the range rests on the vision reading alone."
)


def _downgrade_line_drawing_estimate(estimate: AreaEstimateResult) -> AreaEstimateResult:
    """A block plan is a line drawing; its green/open range is Low confidence whatever the pixels say."""
    confidence = estimate.confidence.model_copy(
        update={
            "label": "Low",
            "score": round(min(estimate.confidence.score, 0.4), 2),
            "reasons": [*estimate.confidence.reasons, LINE_DRAWING_REASON],
        }
    )
    display = estimate.compare_module_display.model_copy(update={"confidence_label": "Low Confidence"})
    return estimate.model_copy(
        update={"confidence": confidence, "compare_module_display": display, "warnings": [*estimate.warnings, LINE_DRAWING_REASON]}
    )


RUN_ID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
RUN_KINDS = ("analysis_runs", "entity_runs")


async def _resolve_master_plan_image(
    upload: UploadFile | None,
    url: str | None,
    run_input_dir: Path,
) -> Path:
    """Store the master plan from an upload or a URL and return its path."""
    settings = get_settings()
    if upload is not None and upload.filename:
        image_path = run_input_dir / _safe_upload_name(upload.filename, fallback_extension=".jpg")
        await _save_upload_file(upload, image_path)
        return image_path

    if url and url.strip():
        try:
            return await run_in_threadpool(
                download_image,
                url.strip(),
                run_input_dir,
                max_bytes=settings.max_image_size_mb * 1024 * 1024,
            )
        except RemoteImageError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - network failures are the caller's problem to retry
            raise HTTPException(status_code=502, detail=f"Could not fetch the image URL: {exc}") from exc

    raise HTTPException(
        status_code=400,
        detail="Provide master_plan_image_file (upload) or master_plan_image_url.",
    )


@app.get("/master-plan/runs/{run_id}/image")
def master_plan_run_image(run_id: str) -> FileResponse:
    """Serve the stored master plan for a run so the UI can display URL-sourced plans."""
    if not RUN_ID_PATTERN.match(run_id):
        raise HTTPException(status_code=404, detail="Unknown run.")

    settings = get_settings()
    for kind in RUN_KINDS:
        run_dir = settings.data_input_dir / kind / run_id
        if not run_dir.is_dir():
            continue
        for candidate in sorted(run_dir.iterdir()):
            if candidate.is_file() and candidate.suffix.lower() in IMAGE_EXTENSIONS:
                return FileResponse(candidate)
    raise HTTPException(status_code=404, detail="No image stored for this run.")


@app.post("/master-plan/analysis")
async def analyse_master_plan(
    master_plan_image_file: UploadFile | None = File(None),
    master_plan_image_url: str | None = Form(None),
    project_json_file: UploadFile | None = File(None),
    run_area_estimate: bool = Form(True),
    site_records_json: str | None = Form(None),
) -> dict:
    """Entity map plus key-value site metrics for the analysis dashboards.

    The plan comes either as an upload or as a public image URL fetched
    server-side. The open/green estimate pipeline runs on the image alone
    (unless disabled); project records raise its confidence. With a project
    JSON the metrics engine also combines project records, the estimate, the
    entity map and the density benchmark dataset. ``site_records_json`` can carry sanction
    figures (FSI, clubhouse area, UDS) that are not in the Datacenter feed.
    """
    settings = get_settings()
    run_id = str(uuid4())

    run_input_dir = ensure_directory(settings.data_input_dir / "analysis_runs" / run_id)
    run_output_dir = ensure_directory(settings.data_output_dir / "analysis_runs" / run_id)

    image_path = await _resolve_master_plan_image(master_plan_image_file, master_plan_image_url, run_input_dir)

    project_json_path: Path | None = None
    if project_json_file is not None and project_json_file.filename:
        project_json_path = run_input_dir / _safe_upload_name(project_json_file.filename, ".json")
        await _save_upload_file(project_json_file, project_json_path)

    try:
        records = SiteRecords.model_validate_json(site_records_json) if site_records_json else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"site_records_json is invalid: {exc}") from exc

    try:
        project = parse_datacenter_json_file(str(project_json_path)) if project_json_path else None
        image_metadata = preprocess_master_plan_image(str(image_path))

        entity_map = extract_master_plan_entities(image_metadata=image_metadata, project=project)
        entity_map_path = run_output_dir / "master_plan_entity_map.json"
        write_json_file(entity_map_path, entity_map.model_dump(mode="json"))

        diagnostics: list[dict] = []
        area_estimate = None
        area_estimate_path: Path | None = None
        if run_area_estimate:
            # Without project records the estimate still runs on the image
            # alone (vision + OpenCV); the missing records lower its confidence.
            estimate_project = project or ParsedProjectMetadata(
                project_id=f"plan-{run_id[:8]}",
                project_name=entity_map.project_name or image_path.stem.replace("-", " ").replace("_", " ").title(),
                source_flags={"has_project_json": False},
            )
            try:
                vision = analyze_master_plan_with_gemini(project=estimate_project, image_metadata=image_metadata)
                segmentation = run_opencv_segmentation(
                    image_metadata=image_metadata, project_id=estimate_project.project_id
                )
                area_estimate = build_area_estimate(
                    project=estimate_project, image_metadata=image_metadata, vision=vision, segmentation=segmentation
                )
                if entity_map.site.drawing_style == "block_plan":
                    area_estimate = _downgrade_line_drawing_estimate(area_estimate)
                area_estimate_path = run_output_dir / "area_estimate.json"
                write_json_file(area_estimate_path, area_estimate.model_dump(mode="json"))
            except Exception as exc:  # noqa: BLE001 - metrics still work without the estimate
                diagnostics.append({"code": "area_estimate_failed", "count": 1, "items": [str(exc)[:200]]})

        # Backend QA agents: review -> fix -> review, best version adopted.
        # The trail is written beside the artifacts; nothing is added here.
        if settings.qa_agents_enabled:
            try:
                entity_map, area_estimate, _ = run_qa_loop(
                    entity_map,
                    area_estimate,
                    image_path=image_metadata.normalized_image_path or str(image_path),
                    project=project,
                    run_id=run_id,
                    output_dir=run_output_dir,
                )
                write_json_file(entity_map_path, entity_map.model_dump(mode="json"))
                if area_estimate is not None and area_estimate_path is not None:
                    write_json_file(area_estimate_path, area_estimate.model_dump(mode="json"))
            except Exception as exc:  # noqa: BLE001 - QA never blocks the analysis
                logger.warning("QA agents skipped for run %s: %s", run_id, exc)

        site_metrics = None
        site_metrics_path: Path | None = None
        if project is not None:
            open_pct, green_pct, confidence = area_inputs_from_estimate(area_estimate)
            site_metrics = build_site_metrics(
                project,
                open_area_percent=open_pct,
                green_area_percent=green_pct,
                area_confidence_label=confidence,
                entity_map=entity_map,
                benchmarks=load_density_benchmarks(),
                records=records,
            )
            site_metrics_path = run_output_dir / "site_metrics.json"
            write_json_file(site_metrics_path, site_metrics.model_dump(mode="json"))
        else:
            diagnostics.append({"code": "project_json_missing", "count": 1})

        qa_trail_path = run_output_dir / "qa_trail.json"
        response = MasterPlanAnalysisResponse(
            run_id=run_id,
            image_url=f"/master-plan/runs/{run_id}/image",
            source_image_url=master_plan_image_url.strip() if master_plan_image_url else None,
            entity_map=entity_map,
            site_metrics=site_metrics,
            area_estimate=area_estimate,
            image_metadata=image_metadata,
            diagnostics=[Diagnostic(code=str(item["code"]), count=int(item.get("count") or 0), items=list(item.get("items") or [])) for item in diagnostics],
            run_artifacts=RunArtifacts(
                input_master_plan_image_path=str(image_path),
                input_project_json_path=str(project_json_path) if project_json_path else None,
                normalized_image_path=image_metadata.normalized_image_path,
                master_plan_entity_map_json_path=str(entity_map_path),
                area_estimate_json_path=str(area_estimate_path) if area_estimate_path else None,
                site_metrics_json_path=str(site_metrics_path) if site_metrics_path else None,
                qa_trail_json_path=str(qa_trail_path) if qa_trail_path.exists() else None,
            ),
        )
        return response.model_dump(mode="json")

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/master-plan/entities")
async def extract_master_plan_entity_map(
    master_plan_image_file: UploadFile | None = File(None),
    master_plan_image_url: str | None = Form(None),
    project_json_file: UploadFile | None = File(None),
) -> dict:
    """Locate every visible entity on one master plan for the hover viewer.

    The plan comes either as an upload or as a public image URL. The project
    JSON is optional; when present it seeds the model with the declared
    amenity list and tags the result with the project id.
    """
    settings = get_settings()
    run_id = str(uuid4())

    run_input_dir = ensure_directory(settings.data_input_dir / "entity_runs" / run_id)
    run_output_dir = ensure_directory(settings.data_output_dir / "entity_runs" / run_id)

    image_path = await _resolve_master_plan_image(master_plan_image_file, master_plan_image_url, run_input_dir)

    project_json_path: Path | None = None
    if project_json_file is not None and project_json_file.filename:
        project_json_path = run_input_dir / _safe_upload_name(project_json_file.filename, ".json")
        await _save_upload_file(project_json_file, project_json_path)

    try:
        project = parse_datacenter_json_file(str(project_json_path)) if project_json_path else None
        image_metadata = preprocess_master_plan_image(str(image_path))

        entity_map = extract_master_plan_entities(image_metadata=image_metadata, project=project)

        if settings.qa_agents_enabled:
            try:
                entity_map, _, _ = run_qa_loop(
                    entity_map,
                    None,
                    image_path=image_metadata.normalized_image_path or str(image_path),
                    project=project,
                    run_id=run_id,
                    output_dir=run_output_dir,
                )
            except Exception as exc:  # noqa: BLE001 - QA never blocks the extraction
                logger.warning("QA agents skipped for run %s: %s", run_id, exc)

        entity_map_path = run_output_dir / "master_plan_entity_map.json"
        write_json_file(entity_map_path, entity_map.model_dump(mode="json"))

        qa_trail_path = run_output_dir / "qa_trail.json"
        response = MasterPlanEntitiesResponse(
            run_id=run_id,
            image_url=f"/master-plan/runs/{run_id}/image",
            source_image_url=master_plan_image_url.strip() if master_plan_image_url else None,
            entity_map=entity_map,
            image_metadata=image_metadata,
            run_artifacts=RunArtifacts(
                input_master_plan_image_path=str(image_path),
                input_project_json_path=str(project_json_path) if project_json_path else None,
                normalized_image_path=image_metadata.normalized_image_path,
                master_plan_entity_map_json_path=str(entity_map_path),
                qa_trail_json_path=str(qa_trail_path) if qa_trail_path.exists() else None,
            ),
        )
        return response.model_dump(mode="json")

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
