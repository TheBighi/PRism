import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { fetchPRDetail } from "../api";
import type { PRDetail as PRDetailType, AnalysisResults, Explanation } from "../types";
import Loading from "../components/Loading";
import ErrorDisplay from "../components/ErrorDisplay";
import RiskBar from "../components/RiskBar";

export default function PRDetail() {
  const { repoId, prNumber } = useParams<{ repoId: string; prNumber: string }>();
  const [pr, setPr] = useState<PRDetailType | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!repoId || !prNumber) return;
    fetchPRDetail(parseInt(repoId, 10), parseInt(prNumber, 10))
      .then(setPr)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [repoId, prNumber]);

  if (loading) return <Loading text="Loading pull request..." />;
  if (error) return (
    <div className="page">
      <div className="page-header">
        <Link to={`/repos/${repoId}`} className="back-link">&larr; Back to repository</Link>
      </div>
      <ErrorDisplay message={error} />
    </div>
  );
  if (!pr) return (
    <div className="page">
      <div className="page-header">
        <Link to={`/repos/${repoId}`} className="back-link">&larr; Back to repository</Link>
      </div>
      <ErrorDisplay message="Pull request not found in database" />
    </div>
  );

  const latestJob = pr.jobs[0];
  const rawResults = latestJob?.results;
  const results: AnalysisResults | null =
    rawResults && typeof rawResults === "object" && !Array.isArray(rawResults)
      ? (rawResults as AnalysisResults)
      : null;
  const rawExplanation = latestJob?.explanation;
  const explanation: Explanation | null =
    rawExplanation && typeof rawExplanation === "object" && !Array.isArray(rawExplanation)
      ? (rawExplanation as Explanation)
      : null;

  return (
    <div className="page">
      <div className="page-header">
        <Link to={`/repos/${repoId}`} className="back-link">
          &larr; Back to repository
        </Link>
        <h1>
          <a href={pr.url} target="_blank" rel="noopener noreferrer" className="pr-link">
            #{pr.number} {pr.title}
          </a>
        </h1>
        <div className="pr-detail__meta">
          <span className={`state-badge state-badge--${pr.state}`}>{pr.state}</span>
          {pr.draft && <span className="state-badge state-badge--draft">draft</span>}
          <span>{pr.author_login}</span>
          <span>{pr.source_branch} &rarr; {pr.target_branch}</span>
          <span>+{pr.additions} / -{pr.deletions}</span>
        </div>
      </div>

      {explanation && (
        <div className="explanation-card">
          <div className="explanation-card__header">
            <h3>AI Analysis</h3>
            <span className={`risk-badge risk-badge--${explanation.overall_risk}`}>
              {explanation.overall_risk}
            </span>
          </div>
          <p className="explanation-card__summary">{explanation.summary}</p>

          {explanation.top_risks && explanation.top_risks.length > 0 && (
            <div className="risks-section">
              <h4>Top Risks</h4>
              {explanation.top_risks.map((risk, i) => (
                <div key={i} className="risk-item">
                  <div className="risk-item__header">
                    <span className={`severity-badge severity-badge--${risk.severity}`}>
                      {risk.severity}
                    </span>
                    <strong>{risk.title}</strong>
                    <span className="risk-item__category">{risk.category}</span>
                  </div>
                  <p className="risk-item__explanation">{risk.explanation}</p>
                  {risk.files.length > 0 && (
                    <div className="risk-item__files">
                      {risk.files.map((f, j) => (
                        <code key={j} className="risk-item__file">{f}</code>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {explanation.recommendation && (
            <div className="recommendation">
              <h4>Recommendation</h4>
              <span className={`priority-badge priority-badge--${explanation.recommendation.priority}`}>
                {explanation.recommendation.priority}
              </span>
              <p>{explanation.recommendation.summary}</p>
              {explanation.recommendation.actions.length > 0 && (
                <ul className="recommendation__actions">
                  {explanation.recommendation.actions.map((action, i) => (
                    <li key={i}>{action}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      )}

      {results && (
        <div className="results-section">
          <h3>Risk Breakdown</h3>
          <div className="results-overall">
            <span className="results-overall__label">Overall Risk Score</span>
            <RiskBar score={results.total ?? 0} size="lg" />
          </div>
          {results.breakdown && typeof results.breakdown === "object" && (
          <div className="breakdown-grid">
            {Object.entries(results.breakdown).map(([key, val]) => (
              <div key={key} className="breakdown-item">
                <div className="breakdown-item__header">
                  <span className="breakdown-item__name">{key.replace(/_/g, " ")}</span>
                  <span className="breakdown-item__score">{val.contribution.toFixed(1)} / {val.weight}</span>
                </div>
                <div className="breakdown-bar">
                  <div
                    className="breakdown-bar__fill"
                    style={{
                      width: `${(val.contribution / val.weight) * 100}%`,
                      backgroundColor: `var(--risk-${val.contribution / val.weight > 0.7 ? "critical" : val.contribution / val.weight > 0.4 ? "high" : "low"})`,
                    }}
                  />
                </div>
                {val.matched_files && val.matched_files.length > 0 && (
                  <div className="breakdown-item__files">
                    {val.matched_files.map((f, i) => (
                      <code key={i}>{f}</code>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
          )}
        </div>
      )}

      {pr.files.length > 0 && (
        <div className="files-section">
          <h3>Changed Files ({pr.files.length})</h3>
          <div className="file-list">
            {pr.files.map((f) => (
              <div key={f.id} className="file-row">
                <span className={`file-status file-status--${f.status}`}>
                  {f.status[0].toUpperCase()}
                </span>
                <span className="file-name">{f.filename}</span>
                <span className="file-changes">
                  <span className="text-add">+{f.additions}</span>
                  <span className="text-del">-{f.deletions}</span>
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {latestJob && (
        <div className="job-status">
          <h3>Latest Analysis Job</h3>
          <div className="job-info">
            <span className={`job-badge job-badge--${latestJob.status}`}>{latestJob.status}</span>
            <span>ID: {latestJob.id}</span>
            {latestJob.error && <span className="text-warn">{latestJob.error}</span>}
          </div>
        </div>
      )}
    </div>
  );
}
