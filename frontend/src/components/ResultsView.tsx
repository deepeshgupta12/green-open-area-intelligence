import {
  AlertTriangle,
  Award,
  Building2,
  CheckCircle2,
  FileJson,
  Leaf,
  Map,
  Trophy,
} from "lucide-react";
import type { CategoryComparisonMatrixRow, MasterPlanComparisonResponse } from "../types";

type ResultsViewProps = {
  result: MasterPlanComparisonResponse;
};

function getWinnerClass(projectSlot?: string, row?: CategoryComparisonMatrixRow) {
  if (!row || row.show_as_insufficient) return "project-score is-muted";
  if (row.show_as_close_call) {
    return projectSlot === row.winner_project_slot ? "project-score is-close-winner" : "project-score";
  }
  if (row.show_as_weak) {
    return projectSlot === row.winner_project_slot ? "project-score is-weak-winner" : "project-score";
  }
  return projectSlot === row.winner_project_slot ? "project-score is-winner" : "project-score";
}

function statusClass(status?: string) {
  if (status === "Close Call") return "status-badge is-close";
  if (status === "Weak Differentiator") return "status-badge is-weak";
  if (status === "Insufficient Evidence") return "status-badge is-insufficient";
  return "status-badge is-clear";
}

function categoryCardClass(row: CategoryComparisonMatrixRow) {
  if (row.show_as_insufficient) return "category-card is-insufficient";
  if (row.show_as_close_call) return "category-card is-close-call";
  if (row.show_as_weak) return "category-card is-weak-differentiator";
  return "category-card";
}

function evidenceItems(row: CategoryComparisonMatrixRow) {
  const seen = new Set<string>();
  const values = [...row.visible_evidence, ...row.declared_evidence, ...row.spatial_evidence]
    .map((value) => value.trim())
    .filter(Boolean)
    .filter((value) => {
      const key = value.toLowerCase();
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  return values.slice(0, 5);
}

export function ResultsView({ result }: ResultsViewProps) {
  const overall = result.overall_recommendation;
  const summary = result.user_friendly_summary;

  return (
    <div className="results">
      <section className="overall-card">
        <div className="overall-icon">
          <Trophy size={28} />
        </div>
        <div>
          <p className="eyebrow">Overall recommendation</p>
          <h2>{overall.frontend_headline || summary.headline}</h2>
          <p>{overall.frontend_summary || summary.short_summary}</p>

          <div className="overall-meta">
            <span>Winner: {overall.winner_project_name}</span>
            <span>{overall.frontend_score_label || overall.rating}</span>
            <span>{overall.rating}</span>
          </div>
        </div>
      </section>

      <section className="best-for-grid">
        {summary.best_for_green_living && (
          <div className="best-for-card">
            <Leaf size={18} />
            <span>{summary.best_for_green_living}</span>
          </div>
        )}
        {summary.best_for_amenities && (
          <div className="best-for-card">
            <Award size={18} />
            <span>{summary.best_for_amenities}</span>
          </div>
        )}
        {summary.best_for_family_living && (
          <div className="best-for-card">
            <Building2 size={18} />
            <span>{summary.best_for_family_living}</span>
          </div>
        )}
        {summary.best_for_access && (
          <div className="best-for-card">
            <Map size={18} />
            <span>{summary.best_for_access}</span>
          </div>
        )}
      </section>

      <section className="project-summary-grid">
        {result.projects.map((project) => (
          <article
            key={project.project_slot}
            className={
              project.project_slot === overall.winner_project_slot
                ? "project-card is-overall-winner"
                : "project-card"
            }
          >
            <div className="project-card-header">
              <span className="slot-pill">Project {project.project_slot}</span>
              {project.project_slot === overall.winner_project_slot && (
                <span className="winner-badge">Overall Winner</span>
              )}
            </div>
            <h3>{project.project_name}</h3>
            <p>
              {project.locality}, {project.city}
            </p>

            <div className="metric-grid">
              <div>
                <span>Green Area</span>
                <strong>{project.green_area_display}</strong>
              </div>
              <div>
                <span>Open Area</span>
                <strong>{project.open_area_display}</strong>
              </div>
              <div>
                <span>Confidence</span>
                <strong>{project.confidence_label}</strong>
              </div>
              <div>
                <span>Overall Rating</span>
                <strong>{project.frontend_score_label || project.overall_category_rating}</strong>
              </div>
            </div>
          </article>
        ))}
      </section>

      <section className="category-section">
        <div className="section-heading">
          <p className="eyebrow">Category comparison</p>
          <h2>Buyer-facing master plan insights</h2>
          <p>
            These cards use frontend-safe copy only. Technical evidence and exact scores are kept
            separately for internal QA.
          </p>
        </div>

        <div className="category-grid">
          {result.category_comparison_matrix.map((row) => {
            const chips = evidenceItems(row);
            return (
              <article key={row.category_key} className={categoryCardClass(row)}>
                <div className="category-card-header">
                  <h3>{row.category_label}</h3>
                  <div className="category-badge-stack">
                    <span className={statusClass(row.category_status)}>{row.category_status}</span>
                    {row.show_winner_badge !== false && !row.show_as_insufficient ? (
                      <span className="winner-badge">Winner: {row.winner_project_name}</span>
                    ) : (
                      <span className="no-winner-badge">No Clear Winner</span>
                    )}
                  </div>
                </div>

                <p className="winner-reason">{row.frontend_winner_reason}</p>

                <div className="evidence-row">
                  <span>Evidence: {row.evidence_strength}</span>
                  <span>Gap: {row.show_as_insufficient ? "—" : row.internal_scoring.score_gap}</span>
                  <span>Confidence: {row.confidence_badge}</span>
                </div>

                {chips.length > 0 && (
                  <div className="evidence-chip-row">
                    {chips.map((item) => (
                      <span key={`${row.category_key}-${item}`} className="evidence-chip">
                        {item}
                      </span>
                    ))}
                  </div>
                )}

                <div className="category-summary">
                  <CheckCircle2 size={18} />
                  <span>{row.frontend_category_summary}</span>
                </div>

                <div className="tradeoff-box">
                  <AlertTriangle size={18} />
                  <span>{row.frontend_tradeoff}</span>
                </div>

                <div className="score-strip">
                  {row.project_scores.map((score) => (
                    <div
                      key={`${row.category_key}-${score.project_slot}`}
                      className={getWinnerClass(score.project_slot, row)}
                    >
                      <span>{score.project_name}</span>
                      <strong>{score.frontend_score_label || score.rating}</strong>
                      <small>{score.score_band || score.rating}</small>
                    </div>
                  ))}
                </div>
              </article>
            );
          })}
        </div>
      </section>

      <details className="internal-qa">
        <summary>
          <FileJson size={18} />
          Internal QA evidence, exact scores and artifacts
        </summary>
        <div className="internal-qa-content">
          <p>
            OpenCV used for frontend copy:{" "}
            <strong>{String(result.internal_evidence_quality.opencv_used_for_frontend_copy)}</strong>
          </p>

          <div className="internal-score-table">
            {result.category_comparison_matrix.map((row) => (
              <div key={`internal-${row.category_key}`} className="internal-score-row">
                <strong>{row.category_label}</strong>
                <span>Winner Score: {row.internal_scoring.winner_score}</span>
                <span>Declared: {row.internal_scoring.declared_score ?? "-"}</span>
                <span>Visible: {row.internal_scoring.visible_score ?? "-"}</span>
                <span>Spatial: {row.internal_scoring.spatial_score ?? "-"}</span>
                <span>Confidence: {row.internal_scoring.confidence_score ?? "-"}</span>
              </div>
            ))}
          </div>

          {result.internal_evidence_quality.project_evidence.map((project) => (
            <div key={project.project_slot} className="internal-project">
              <h4>
                Project {project.project_slot}: {project.project_name}
              </h4>
              <p>Confidence: {project.confidence_label}</p>
              <p>Understanding confidence: {project.master_plan_understanding_confidence || "-"}</p>
              <p>Manual correction recommended: {String(project.manual_correction_recommended || false)}</p>
              <ul>
                {project.technical_warnings.slice(0, 4).map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </div>
          ))}

          <pre>{JSON.stringify(result.run_artifacts, null, 2)}</pre>
        </div>
      </details>
    </div>
  );
}
