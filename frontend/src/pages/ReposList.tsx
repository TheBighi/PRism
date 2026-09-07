import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchIgnoredRepos, fetchRepos, ignoreRepo, restoreRepo } from "../api";
import type { RepoSummary } from "../types";
import Loading from "../components/Loading";
import ErrorDisplay from "../components/ErrorDisplay";
import RiskBar from "../components/RiskBar";

export default function ReposList() {
  const [repos, setRepos] = useState<RepoSummary[]>([]);
  const [ignoredRepos, setIgnoredRepos] = useState<RepoSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionRepoId, setActionRepoId] = useState<number | null>(null);

  useEffect(() => {
    Promise.all([fetchRepos(), fetchIgnoredRepos()])
      .then(([visible, ignored]) => {
        setRepos(visible);
        setIgnoredRepos(ignored);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  async function changeIgnoredState(repo: RepoSummary, ignored: boolean) {
    setActionRepoId(repo.id);
    setError(null);
    try {
      if (ignored) {
        await ignoreRepo(repo.id);
        setRepos((current) => current.filter((item) => item.id !== repo.id));
        setIgnoredRepos((current) => [repo, ...current]);
      } else {
        await restoreRepo(repo.id);
        setIgnoredRepos((current) => current.filter((item) => item.id !== repo.id));
        setRepos((current) => [repo, ...current]);
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
          {repos.length} {repos.length === 1 ? "repository" : "repositories"} shown
        </p>
      </div>

      {error && <ErrorDisplay message={error} />}

      {repos.length === 0 ? (
        <div className="empty-state">
          <p>{ignoredRepos.length > 0
            ? "All available repositories are ignored. Restore one from the list below."
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
                onClick={() => void changeIgnoredState(repo, true)}
              >
                {actionRepoId === repo.id ? "Ignoring..." : "Ignore repository"}
              </button>
            </article>
          ))}
        </div>
      )}

      {ignoredRepos.length > 0 && (
        <section className="ignored-repos">
          <div className="ignored-repos__header">
            <h2>Ignored repositories</h2>
            <span>{ignoredRepos.length}</span>
          </div>
          <div className="ignored-repos__list">
            {ignoredRepos.map((repo) => (
              <div className="ignored-repo" key={repo.id}>
                <span><strong>{repo.owner}</strong>/{repo.name}</span>
                <button
                  type="button"
                  disabled={actionRepoId === repo.id}
                  onClick={() => void changeIgnoredState(repo, false)}
                >
                  {actionRepoId === repo.id ? "Restoring..." : "Restore"}
                </button>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
