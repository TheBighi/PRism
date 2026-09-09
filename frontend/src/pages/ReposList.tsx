import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  disableRepoAnalysis,
  enableRepoAnalysis,
  fetchAvailableRepos,
  fetchRepos,
} from "../api";
import type { RepoSummary } from "../types";
import Loading from "../components/Loading";
import ErrorDisplay from "../components/ErrorDisplay";
import RiskBar from "../components/RiskBar";

export default function ReposList() {
  const [repos, setRepos] = useState<RepoSummary[]>([]);
  const [availableRepos, setAvailableRepos] = useState<RepoSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionRepoId, setActionRepoId] = useState<number | null>(null);

  useEffect(() => {
    Promise.all([fetchRepos(), fetchAvailableRepos()])
      .then(([selected, available]) => {
        setRepos(selected);
        setAvailableRepos(available);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  async function changeAnalysisState(repo: RepoSummary, enabled: boolean) {
    setActionRepoId(repo.id);
    setError(null);
    try {
      if (enabled) {
        await enableRepoAnalysis(repo.id);
        setAvailableRepos((current) => current.filter((item) => item.id !== repo.id));
        setRepos((current) => [{ ...repo, analysis_enabled: true }, ...current]);
      } else {
        await disableRepoAnalysis(repo.id);
        setRepos((current) => current.filter((item) => item.id !== repo.id));
        setAvailableRepos((current) => [{ ...repo, analysis_enabled: false }, ...current]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update repository preference");
    } finally {
      setActionRepoId(null);
    }
  }

  if (loading) return <Loading text="Loading repositories..." />;
  return (
    <div className="page">
      <div className="page-header">
        <h1>Repositories</h1>
        <p className="page-subtitle">
          Choose exactly which installed repositories PRism may analyze
        </p>
      </div>

      {error && <ErrorDisplay message={error} />}

      {repos.length === 0 ? (
        <div className="empty-state">
          <p>{availableRepos.length > 0
            ? "No repositories are being analyzed. Add one from the available list below."
            : "No repositories yet. Install the PRism GitHub App on a repository to get started."}</p>
        </div>
      ) : (
        <div className="repo-grid">
          {repos.map((repo) => (
            <article key={repo.id} className="repo-card">
              <Link to={`/repos/${repo.id}`} className="repo-card__link">
                <div className="repo-card__header">
                  <div className="repo-card__name">
                    <span className="repo-card__owner">{repo.owner}</span>
                    <span className="repo-card__slash">/</span>
                    <span className="repo-card__repo">{repo.name}</span>
                  </div>
                  <div
                    className={`repo-card__health-badge ${
                      repo.health_score >= 80
                        ? "repo-card__health-badge--good"
                        : repo.health_score >= 60
                        ? "repo-card__health-badge--warn"
                        : "repo-card__health-badge--bad"
                    }`}
                  >
                    {repo.health_score}
                  </div>
                </div>

                <div className="repo-card__stats">
                  <span className="repo-card__stat">
                    <strong>{repo.pr_count}</strong> PRs
                  </span>
                  <span className="repo-card__stat">
                    <strong>{repo.open_pr_count}</strong> open
                  </span>
                  {repo.hotspot_count > 0 && (
                    <span className="repo-card__stat repo-card__stat--warn">
                      <strong>{repo.hotspot_count}</strong> hotspots
                    </span>
                  )}
                </div>

                {repo.avg_risk_score !== null && (
                  <div className="repo-card__risk">
                    <span className="repo-card__risk-label">Avg Risk</span>
                    <RiskBar score={repo.avg_risk_score} size="sm" showLabel={false} />
                  </div>
                )}
              </Link>
              <button
                className="repo-card__action"
                type="button"
                disabled={actionRepoId === repo.id}
                onClick={() => void changeAnalysisState(repo, false)}
              >
                {actionRepoId === repo.id ? "Updating..." : "Stop analyzing"}
              </button>
            </article>
          ))}
        </div>
      )}

      {availableRepos.length > 0 && (
        <section className="available-repos">
          <div className="available-repos__header">
            <div>
              <h2>Available repositories</h2>
              <p>Webhook events are ignored until you enable analysis.</p>
            </div>
            <span>{availableRepos.length}</span>
          </div>
          <div className="available-repos__list">
            {availableRepos.map((repo) => (
              <div className="available-repo" key={repo.id}>
                <span><strong>{repo.owner}</strong>/{repo.name}</span>
                <button
                  type="button"
                  disabled={actionRepoId === repo.id}
                  onClick={() => void changeAnalysisState(repo, true)}
                >
                  {actionRepoId === repo.id ? "Enabling..." : "Analyze"}
                </button>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
