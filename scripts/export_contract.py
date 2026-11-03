"""Write the JSON Schema of the API contract to docs/contract/.

  python scripts/export_contract.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

from app.schemas.analysis_response_schema import MasterPlanAnalysisResponse, MasterPlanEntitiesResponse  # noqa: E402


def main() -> None:
    out_dir = ROOT_DIR / "docs" / "contract"
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, model in (("master_plan_analysis", MasterPlanAnalysisResponse), ("master_plan_entities", MasterPlanEntitiesResponse)):
        path = out_dir / f"{name}.schema.json"
        path.write_text(json.dumps(model.model_json_schema(), indent=2), encoding="utf-8")
        print("wrote", path.relative_to(ROOT_DIR))


if __name__ == "__main__":
    main()
