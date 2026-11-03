import { useMemo, useState } from "react";
import { Loader2, RefreshCcw, UploadCloud } from "lucide-react";
import { MasterPlanExplorer } from "./components/MasterPlanExplorer";
import type { ExplorerSlot } from "./components/MasterPlanExplorer";
import { ProjectUploadCard } from "./components/ProjectUploadCard";
import { ResultsView } from "./components/ResultsView";
import { compareMasterPlans } from "./lib/api";
import type { MasterPlanComparisonResponse } from "./types";
import "./styles.css";

export default function App() {
  const [projectAJson, setProjectAJson] = useState<File | null>(null);
  const [projectAImage, setProjectAImage] = useState<File | null>(null);

  const [projectBJson, setProjectBJson] = useState<File | null>(null);
  const [projectBImage, setProjectBImage] = useState<File | null>(null);

  const [projectCJson, setProjectCJson] = useState<File | null>(null);
  const [projectCImage, setProjectCImage] = useState<File | null>(null);

  const [useAiNarrative, setUseAiNarrative] = useState(true);
  const [useAiEntityExtraction, setUseAiEntityExtraction] = useState(false);
  const [result, setResult] = useState<MasterPlanComparisonResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const canSubmit = useMemo(() => {
    return Boolean(
      projectAJson &&
        projectAImage &&
        projectBJson &&
        projectBImage &&
        projectCJson &&
        projectCImage &&
        !isLoading
    );
  }, [
    projectAJson,
    projectAImage,
    projectBJson,
    projectBImage,
    projectCJson,
    projectCImage,
    isLoading,
  ]);

  const explorerSlots = useMemo<ExplorerSlot[]>(
    () => [
      { slot: "A", title: "First project", imageFile: projectAImage, jsonFile: projectAJson },
      { slot: "B", title: "Second project", imageFile: projectBImage, jsonFile: projectBJson },
      { slot: "C", title: "Third project", imageFile: projectCImage, jsonFile: projectCJson },
    ],
    [projectAImage, projectAJson, projectBImage, projectBJson, projectCImage, projectCJson]
  );

  async function handleSubmit() {
    if (
      !projectAJson ||
      !projectAImage ||
      !projectBJson ||
      !projectBImage ||
      !projectCJson ||
      !projectCImage
    ) {
      setError("Please upload JSON and master plan image for all 3 projects.");
      return;
    }

    setError(null);
    setIsLoading(true);
    setResult(null);

    try {
      const response = await compareMasterPlans({
        projectAJson,
        projectAImage,
        projectBJson,
        projectBImage,
        projectCJson,
        projectCImage,
        useAiNarrative,
        useAiEntityExtraction,
      });

      setResult(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setIsLoading(false);
    }
  }

  function handleReset() {
    setProjectAJson(null);
    setProjectAImage(null);
    setProjectBJson(null);
    setProjectBImage(null);
    setProjectCJson(null);
    setProjectCImage(null);
    setResult(null);
    setError(null);
  }

  return (
    <main className="app-shell">
      <section className="hero">
        <div>
          <p className="eyebrow">Square Yards Internal Intelligence</p>
          <h1>Master Plan Comparison Engine</h1>
          <p>
            Upload 3 Datacenter JSON files and 3 master plan images to compare
            green living, open space, density comfort, amenities, lifestyle,
            family use, leisure, access, and sustainability signals.
          </p>
        </div>
      </section>

      <section className="upload-grid">
        <ProjectUploadCard
          slot="A"
          title="First project"
          jsonFile={projectAJson}
          imageFile={projectAImage}
          setJsonFile={setProjectAJson}
          setImageFile={setProjectAImage}
        />
        <ProjectUploadCard
          slot="B"
          title="Second project"
          jsonFile={projectBJson}
          imageFile={projectBImage}
          setJsonFile={setProjectBJson}
          setImageFile={setProjectBImage}
        />
        <ProjectUploadCard
          slot="C"
          title="Third project"
          jsonFile={projectCJson}
          imageFile={projectCImage}
          setJsonFile={setProjectCJson}
          setImageFile={setProjectCImage}
        />
      </section>

      <section className="control-bar">
        <div className="toggle-stack">
          <label className="toggle-row">
            <input
              type="checkbox"
              checked={useAiNarrative}
              onChange={(event) => setUseAiNarrative(event.target.checked)}
            />
            <span>Use Gemini narrative for frontend copy</span>
          </label>
          <label className="toggle-row">
            <input
              type="checkbox"
              checked={useAiEntityExtraction}
              onChange={(event) => setUseAiEntityExtraction(event.target.checked)}
            />
            <span>Map master plan entities during compare (slower; adds a hover map per project)</span>
          </label>
        </div>

        <div className="button-row">
          <button className="secondary-button" onClick={handleReset}>
            <RefreshCcw size={18} />
            Reset
          </button>
          <button
            className="primary-button"
            disabled={!canSubmit}
            onClick={handleSubmit}
          >
            {isLoading ? <Loader2 className="spin" size={18} /> : <UploadCloud size={18} />}
            {isLoading ? "Comparing..." : "Compare Master Plans"}
          </button>
        </div>
      </section>

      {error && <section className="error-box">{error}</section>}

      {result && <ResultsView result={result} />}

      <MasterPlanExplorer slots={explorerSlots} prefilled={result?.project_entity_maps} />
    </main>
  );
}
