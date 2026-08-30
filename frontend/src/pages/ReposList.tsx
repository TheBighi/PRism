import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchRepos } from "../api";
import type { RepoSummary } from "../types";
import Loading from "../components/Loading";
import ErrorDisplay from "../components/ErrorDisplay";
import RiskBar from "../components/RiskBar";

export default function ReposList() {
  const [repos, setRepos] = useState<RepoSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchRepos()
      .then(setRepos)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <Loading text="Loading repositories..." />;
  if (error) return <ErrorDisplay message={error} />;

  return (
    <div className="page">
      <div className="page-header">
        <h1>Repositories</h1>
        <p className="page-subtitle">
          {repos.length} repository {repos.length !== 1 ? "repositories" : "repository"} tracked
        </p>
      </div>

      {repos.length === 0 ? (
        <div className="empty-state">
          <p>No repositories yet. Install the PRism GitHub App on a repository to get started.</p>
        </div>
      ) : (
        <div className="repo-grid">
          {repos.map((repo) => (
            <Link
              key={repo.id}
              to={`/repos/${repo.id}`}
              className="repo-card"
            >
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
          ))}
        </div>
      )}
    </div>
  );
}
