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
import type { MasterPlanComparisonResponse } from "../types";

type ResultsViewProps = {
  result: MasterPlanComparisonResponse;
};

function getWinnerClass(projectSlot?: string, winnerSlot?: string) {
  return projectSlot === winnerSlot ? "project-score is-winner" : "project-score";
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
            <span>Score: {overall.score}</span>
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
                <span>Score</span>
                <strong>{project.overall_category_score}</strong>
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
            These cards use frontend-safe copy only. Technical evidence is kept
            separately for internal QA.
          </p>
        </div>

        <div className="category-grid">
          {result.category_comparison_matrix.map((row) => (
            <article key={row.category_key} className="category-card">
              <div className="category-card-header">
                <h3>{row.category_label}</h3>
                <span className="winner-badge">
                  Winner: {row.winner_project_name}
                </span>
              </div>

              <p className="winner-reason">{row.frontend_winner_reason}</p>

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
                    className={getWinnerClass(
                      score.project_slot,
                      row.winner_project_slot
                    )}
                  >
                    <span>{score.project_name}</span>
                    <strong>{score.score}</strong>
                    <small>{score.rating}</small>
                  </div>
                ))}
              </div>
            </article>
          ))}
        </div>
      </section>

      <details className="internal-qa">
        <summary>
          <FileJson size={18} />
          Internal QA evidence and artifacts
        </summary>
        <div className="internal-qa-content">
          <p>
            OpenCV used for frontend copy:{" "}
            <strong>
              {String(result.internal_evidence_quality.opencv_used_for_frontend_copy)}
            </strong>
          </p>

          {result.internal_evidence_quality.project_evidence.map((project) => (
            <div key={project.project_slot} className="internal-project">
              <h4>
                Project {project.project_slot}: {project.project_name}
              </h4>
              <p>Confidence: {project.confidence_label}</p>
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
