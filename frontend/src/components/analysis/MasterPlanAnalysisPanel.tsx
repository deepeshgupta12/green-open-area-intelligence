import { useState } from "react";
import { apiUrl } from "../../lib/api";
import type { MasterPlanAnalysisResponse } from "../../types";
import { MasterPlanEntityViewer, describeDiagnostic } from "../MasterPlanEntityViewer";
import { DensityProfile } from "./DensityProfile";
import { LandAllocationSankey } from "./LandAllocationSankey";
import { SiteZoningCard } from "./SiteZoningCard";

type MasterPlanAnalysisPanelProps = {
  title: string;
  /** Local upload when there is one; otherwise the API's stored copy is shown. */
  imageFile: File | null;
  analysis: MasterPlanAnalysisResponse;
};

export function MasterPlanAnalysisPanel({ title, imageFile, analysis }: MasterPlanAnalysisPanelProps) {
  const metrics = analysis.site_metrics;
  // With no project JSON the hover map is the whole result, so open it at once.
  const [viewerOpen, setViewerOpen] = useState(!metrics);
  const servedImageUrl = imageFile ? null : apiUrl(analysis.image_url);

  return (
    <div className="analysis-root">
      {metrics ? (
        <SiteZoningCard
          metrics={metrics}
          imageFile={imageFile}
          imageUrl={servedImageUrl}
          onInspect={() => setViewerOpen((open) => !open)}
        />
      ) : (
        <div className="analysis-card">
          <p className="entity-muted">
            Upload the project&apos;s Datacenter JSON alongside the plan to get parcel, density and allocation metrics. The entity map below works without it.
          </p>
          <button type="button" className="secondary-button" onClick={() => setViewerOpen((open) => !open)}>
            {viewerOpen ? "Hide master plan" : "Inspect master plan"}
          </button>
        </div>
      )}

      {analysis.diagnostics.length > 0 && (
        <ul className="analysis-diagnostics">
          {analysis.diagnostics.map((diagnostic, index) => (
            <li key={`${diagnostic.code}-${index}`}>
              {diagnostic.code === "area_estimate_failed"
                ? "The open-area estimate could not be produced for this run; parcel figures are shown without it."
                : diagnostic.code === "project_json_missing"
                  ? "No project JSON was supplied."
                  : describeDiagnostic(diagnostic)}
            </li>
          ))}
        </ul>
      )}

      {viewerOpen && (
        <MasterPlanEntityViewer title={title} imageFile={imageFile} imageUrl={servedImageUrl} entityMap={analysis.entity_map} />
      )}

      {metrics && <DensityProfile metrics={metrics} />}
      {metrics && <LandAllocationSankey metrics={metrics} />}
    </div>
  );
}
