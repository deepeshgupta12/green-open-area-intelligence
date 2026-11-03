import { useState } from "react";
import { FileJson } from "lucide-react";
import { apiUrl } from "../../lib/api";
import type { MasterPlanAnalysisResponse } from "../../types";
import { MasterPlanEntityViewer, describeDiagnostic } from "../MasterPlanEntityViewer";
import { AmenitySection } from "./AmenitySection";
import { DensityProfile } from "./DensityProfile";
import { LandAllocationSankey } from "./LandAllocationSankey";
import { LandUseSection } from "./LandUseSection";
import { MasterPlanCompositionCard } from "./MasterPlanCompositionCard";
import { SiteZoningCard } from "./SiteZoningCard";
import { SpatialAccessSection } from "./SpatialAccessSection";

type MasterPlanAnalysisPanelProps = {
  title: string;
  /** Local upload when there is one; otherwise the API's stored copy is shown. */
  imageFile: File | null;
  analysis: MasterPlanAnalysisResponse;
};

export function MasterPlanAnalysisPanel({ title, imageFile, analysis }: MasterPlanAnalysisPanelProps) {
  const metrics = analysis.site_metrics;
  const entityMap = analysis.entity_map;
  const [viewerOpen, setViewerOpen] = useState(false);
  const servedImageUrl = imageFile ? null : apiUrl(analysis.image_url);
  const toggleViewer = () => setViewerOpen((open) => !open);

  return (
    <div className="analysis-root">
      {metrics ? (
        <SiteZoningCard metrics={metrics} imageFile={imageFile} imageUrl={servedImageUrl} onInspect={toggleViewer} />
      ) : (
        <MasterPlanCompositionCard
          entityMap={entityMap}
          imageFile={imageFile}
          imageUrl={servedImageUrl}
          viewerOpen={viewerOpen}
          onInspect={toggleViewer}
        />
      )}

      {!metrics && (
        <div className="cta-banner">
          <FileJson size={18} aria-hidden="true" />
          <p>
            <strong>Add the project&apos;s Datacenter JSON</strong> to unlock the site zoning, home mix, density benchmark
            and land allocation dashboards, and to back the green and open area estimate with project records.
          </p>
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
        <MasterPlanEntityViewer title={title} imageFile={imageFile} imageUrl={servedImageUrl} entityMap={entityMap} />
      )}

      <LandUseSection entityMap={entityMap} metrics={metrics} estimate={analysis.area_estimate} />

      {metrics && (
        <MasterPlanCompositionCard
          entityMap={entityMap}
          imageFile={imageFile}
          imageUrl={servedImageUrl}
          viewerOpen={viewerOpen}
          onInspect={toggleViewer}
          showPlan={false}
        />
      )}

      <AmenitySection entityMap={entityMap} />
      <SpatialAccessSection entityMap={entityMap} />

      {metrics && <DensityProfile metrics={metrics} />}
      {metrics && <LandAllocationSankey metrics={metrics} />}
    </div>
  );
}
