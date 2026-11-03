import { useState } from "react";
import { Link2, Loader2, RefreshCcw, ScanSearch, Upload } from "lucide-react";
import { analyseMasterPlan } from "../lib/api";
import type { MasterPlanAnalysisResponse } from "../types";
import { FileInput } from "./FileInput";
import { MasterPlanAnalysisPanel } from "./analysis/MasterPlanAnalysisPanel";

type SourceMode = "url" | "upload";

type RunState = {
  status: "idle" | "loading" | "done" | "error";
  analysis: MasterPlanAnalysisResponse | null;
  error: string | null;
  imageFile: File | null;
  title: string;
};

const IDLE: RunState = { status: "idle", analysis: null, error: null, imageFile: null, title: "" };

function looksLikeHttpUrl(value: string): boolean {
  try {
    const parsed = new URL(value.trim());
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return false;
  }
}

function titleFromUrl(value: string): string {
  try {
    const name = new URL(value).pathname.split("/").filter(Boolean).pop() ?? "Master plan";
    return decodeURIComponent(name).replace(/\.[a-z0-9]+$/i, "").replace(/[-_]+/g, " ");
  } catch {
    return "Master plan";
  }
}

/** Standalone entry point: paste a plan URL or pick a file, optionally add the project JSON, run. */
export function MasterPlanSourceCard() {
  const [mode, setMode] = useState<SourceMode>("url");
  const [url, setUrl] = useState("");
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [jsonFile, setJsonFile] = useState<File | null>(null);
  const [run, setRun] = useState<RunState>(IDLE);

  const urlValid = looksLikeHttpUrl(url);
  const canRun = run.status !== "loading" && (mode === "url" ? urlValid : Boolean(imageFile));

  function handleReset() {
    setUrl("");
    setImageFile(null);
    setJsonFile(null);
    setRun(IDLE);
  }

  async function handleRun() {
    if (!canRun) return;
    const sourceFile = mode === "upload" ? imageFile : null;
    const title = mode === "upload" ? imageFile?.name.replace(/\.[a-z0-9]+$/i, "") ?? "Master plan" : titleFromUrl(url);
    setRun({ status: "loading", analysis: null, error: null, imageFile: sourceFile, title });

    try {
      const analysis = await analyseMasterPlan({
        image: sourceFile,
        imageUrl: mode === "url" ? url : null,
        projectJson: jsonFile,
      });
      setRun({ status: "done", analysis, error: null, imageFile: sourceFile, title });
    } catch (err) {
      setRun({
        status: "error",
        analysis: null,
        error: err instanceof Error ? err.message : "Master plan analysis failed.",
        imageFile: sourceFile,
        title,
      });
    }
  }

  return (
    <div className="explorer-card source-card">
      <div className="explorer-card-header">
        <div>
          <span className="slot-pill">Any plan</span>
          <h3>Analyse a master plan from a link or a file</h3>
          <p className="entity-muted">
            Paste a public image URL (for example a Square Yards master plan image) or upload the image. Add the
            project&apos;s Datacenter JSON to unlock parcel, density and allocation metrics.
          </p>
        </div>
        <div className="button-row">
          <button type="button" className="secondary-button" onClick={handleReset} disabled={run.status === "loading"}>
            <RefreshCcw size={18} />
            Reset
          </button>
          <button type="button" className="primary-button" disabled={!canRun} onClick={handleRun}>
            {run.status === "loading" ? <Loader2 className="spin" size={18} /> : <ScanSearch size={18} />}
            {run.status === "loading" ? "Analysing plan..." : run.status === "done" ? "Run again" : "Run analysis"}
          </button>
        </div>
      </div>

      <div className="source-form">
        <div className="source-modes" role="tablist" aria-label="Master plan source">
          <button
            type="button"
            role="tab"
            aria-selected={mode === "url"}
            className={mode === "url" ? "is-active" : ""}
            onClick={() => setMode("url")}
          >
            <Link2 size={14} /> Image URL
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === "upload"}
            className={mode === "upload" ? "is-active" : ""}
            onClick={() => setMode("upload")}
          >
            <Upload size={14} /> Upload image
          </button>
        </div>

        <div className="source-inputs">
          {mode === "url" ? (
            <label className="url-input">
              <span>Master plan image URL</span>
              <input
                type="url"
                inputMode="url"
                placeholder="https://static.squareyards.com/.../project-master-plan-image1.jpg"
                value={url}
                onChange={(event) => setUrl(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") handleRun();
                }}
              />
              <small>{url && !urlValid ? "Enter a full http(s) link to an image." : "The image is fetched by the server, so it must be publicly reachable."}</small>
            </label>
          ) : (
            <FileInput
              label="Master plan image"
              accept="image/png,image/jpeg,image/jpg,image/webp"
              file={imageFile}
              onChange={setImageFile}
            />
          )}
          <FileInput label="Datacenter JSON (optional)" accept=".json,application/json" file={jsonFile} onChange={setJsonFile} />
        </div>
      </div>

      {run.status === "error" && <div className="error-box">{run.error}</div>}

      {run.status === "done" && run.analysis && (
        <MasterPlanAnalysisPanel
          title={run.analysis.site_metrics?.project_name || run.analysis.entity_map.project_name || run.title}
          imageFile={run.imageFile}
          analysis={run.analysis}
        />
      )}
    </div>
  );
}
