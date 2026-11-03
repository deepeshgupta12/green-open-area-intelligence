import { useEffect, useState } from "react";
import { Loader2, ScanSearch } from "lucide-react";
import { analyseMasterPlan, extractMasterPlanEntities } from "../lib/api";
import type { MasterPlanAnalysisResponse, MasterPlanEntityMap } from "../types";
import { MasterPlanAnalysisPanel } from "./analysis/MasterPlanAnalysisPanel";

export type ExplorerSlot = {
  slot: "A" | "B" | "C";
  title: string;
  imageFile: File | null;
  jsonFile: File | null;
};

type MasterPlanExplorerProps = {
  slots: ExplorerSlot[];
  prefilled?: Record<string, MasterPlanEntityMap | null>;
};

type SlotState = {
  status: "idle" | "loading" | "done" | "error";
  analysis: MasterPlanAnalysisResponse | null;
  error: string | null;
  sourceFileKey: string | null;
};

function fileKey(file: File | null): string | null {
  return file ? `${file.name}:${file.size}:${file.lastModified}` : null;
}

const EMPTY: SlotState = { status: "idle", analysis: null, error: null, sourceFileKey: null };

function analysisFromEntityMap(map: MasterPlanEntityMap): MasterPlanAnalysisResponse {
  return {
    run_id: "compare-run",
    entity_map: map,
    site_metrics: null,
    area_estimate: null,
    image_metadata: {},
    diagnostics: [],
    run_artifacts: {},
  };
}

export function MasterPlanExplorer({ slots, prefilled }: MasterPlanExplorerProps) {
  const [states, setStates] = useState<Record<string, SlotState>>({});

  // Entity maps returned by the compare run pre-populate the viewer so the
  // user does not pay for a second Gemini call.
  useEffect(() => {
    if (!prefilled) return;
    setStates((current) => {
      const next = { ...current };
      slots.forEach(({ slot, imageFile }) => {
        const map = prefilled[slot];
        if (map && !(current[slot]?.analysis?.site_metrics)) {
          next[slot] = { status: "done", analysis: analysisFromEntityMap(map), error: null, sourceFileKey: fileKey(imageFile) };
        }
      });
      return next;
    });
  }, [prefilled, slots]);

  // Drop stale results when the image for a slot is replaced.
  useEffect(() => {
    setStates((current) => {
      let changed = false;
      const next = { ...current };
      slots.forEach(({ slot, imageFile }) => {
        const state = current[slot];
        if (state && state.sourceFileKey && state.sourceFileKey !== fileKey(imageFile)) {
          next[slot] = EMPTY;
          changed = true;
        }
      });
      return changed ? next : current;
    });
  }, [slots]);

  async function runAnalysis(slot: ExplorerSlot) {
    if (!slot.imageFile) return;
    const key = fileKey(slot.imageFile);
    setStates((current) => ({
      ...current,
      [slot.slot]: { status: "loading", analysis: null, error: null, sourceFileKey: key },
    }));

    try {
      const analysis = slot.jsonFile
        ? await analyseMasterPlan({ image: slot.imageFile, projectJson: slot.jsonFile })
        : analysisFromEntityMap((await extractMasterPlanEntities({ image: slot.imageFile })).entity_map);
      setStates((current) => ({
        ...current,
        [slot.slot]: { status: "done", analysis, error: null, sourceFileKey: key },
      }));
    } catch (err) {
      setStates((current) => ({
        ...current,
        [slot.slot]: {
          status: "error",
          analysis: null,
          error: err instanceof Error ? err.message : "Master plan analysis failed.",
          sourceFileKey: key,
        },
      }));
    }
  }

  const slotsWithImages = slots.filter((slot) => slot.imageFile);
  if (slotsWithImages.length === 0) return null;

  return (
    <section className="explorer-section">
      <div className="section-heading">
        <p className="eyebrow">Master plan analysis</p>
        <h2>Site zoning, density and land allocation, straight from the plan</h2>
        <p>
          Locate every wing, court, pool, garden, road, gate and utility yard on an uploaded master plan, then read the
          parcel, density and open-space figures behind it. Everything shown is a key-value fact with its source; nothing is
          model-written copy.
        </p>
      </div>

      <div className="explorer-grid">
        {slotsWithImages.map((slot) => {
          const state = states[slot.slot] ?? EMPTY;
          return (
            <div key={slot.slot} className="explorer-card">
              <div className="explorer-card-header">
                <div>
                  <span className="slot-pill">Project {slot.slot}</span>
                  <h3>{slot.title}</h3>
                  <p className="entity-muted">
                    {slot.imageFile?.name}
                    {slot.jsonFile ? ` · ${slot.jsonFile.name}` : " · no project JSON (entity map only)"}
                  </p>
                </div>
                <button type="button" className="primary-button" disabled={state.status === "loading"} onClick={() => runAnalysis(slot)}>
                  {state.status === "loading" ? <Loader2 className="spin" size={18} /> : <ScanSearch size={18} />}
                  {state.status === "loading" ? "Analysing plan..." : state.status === "done" ? "Re-run analysis" : "Analyse master plan"}
                </button>
              </div>

              {state.status === "error" && <div className="error-box">{state.error}</div>}

              {state.status === "done" && state.analysis && (
                <MasterPlanAnalysisPanel
                  title={state.analysis.site_metrics?.project_name || state.analysis.entity_map.project_name || slot.title}
                  imageFile={slot.imageFile}
                  analysis={state.analysis}
                />
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
