import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { fetchRepoDetail } from "../api";
import type { RepoSummary, RepoHealth, PRSummary, HotspotFile } from "../types";
import Loading from "../components/Loading";
import ErrorDisplay from "../components/ErrorDisplay";
import HealthCard from "../components/HealthCard";
import StatCard from "../components/StatCard";
import RiskBar from "../components/RiskBar";

interface RepoDetailData {
  repo: RepoSummary;
  health: RepoHealth;
  pull_requests: PRSummary[];
  hotspots: HotspotFile[];
}

export default function RepoDetail() {
  const { repoId } = useParams<{ repoId: string }>();
  const [data, setData] = useState<RepoDetailData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"prs" | "hotspots">("prs");

  useEffect(() => {
    if (!repoId) return;
    fetchRepoDetail(parseInt(repoId, 10))
      .then(setData)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [repoId]);

  if (loading) return <Loading text="Loading repository..." />;
  if (error) return (
    <div className="page">
      <div className="page-header">
        <Link to="/" className="back-link">&larr; All Repos</Link>
      </div>
      <ErrorDisplay message={error} />
    </div>
  );
  if (!data) return (
    <div className="page">
      <div className="page-header">
        <Link to="/" className="back-link">&larr; All Repos</Link>
      </div>
      <ErrorDisplay message="Repository not found in database" />
    </div>
  );

  const { repo, health, pull_requests: prs, hotspots } = data;
  const openPRs = prs.filter((p) => p.state === "open");
  const closedPRs = prs.filter((p) => p.state !== "open");

  return (
    <div className="page">
      <div className="page-header">
        <Link to="/" className="back-link">&larr; All Repos</Link>
        <h1>
          <a href={repo.url} target="_blank" rel="noopener noreferrer" className="repo-link">
            {repo.owner}/{repo.name}
          </a>
        </h1>
      </div>

      <div className="health-overview">
        <HealthCard score={health.health_score} />
        <div className="health-stats">
          <StatCard label="Total PRs" value={health.total_prs} />
          <StatCard label="Open PRs" value={health.open_prs} />
          <StatCard label="Merged" value={health.merged_prs} />
          <StatCard label="Avg Risk" value={health.avg_risk_score ?? "N/A"} accent={health.avg_risk_score !== null && health.avg_risk_score >= 50} />
          <StatCard label="High Risk PRs" value={health.high_risk_prs} accent={health.high_risk_prs > 0} />
          <StatCard label="Failed Jobs" value={health.failed_jobs} accent={health.failed_jobs > 0} />
        </div>
      </div>

      <div className="tabs">
        <button
          className={`tab ${activeTab === "prs" ? "tab--active" : ""}`}
          onClick={() => setActiveTab("prs")}
        >
          Pull Requests ({prs.length})
        </button>
        <button
          className={`tab ${activeTab === "hotspots" ? "tab--active" : ""}`}
          onClick={() => setActiveTab("hotspots")}
        >
          Hotspot Files ({hotspots.length})
        </button>
      </div>

      {activeTab === "prs" && (
        <div className="pr-list">
          {prs.length === 0 ? (
            <div className="empty-state">No pull requests found.</div>
          ) : (
            <>
              {openPRs.length > 0 && (
                <div className="pr-section">
                  <h3 className="pr-section__title">Open ({openPRs.length})</h3>
                  {openPRs.map((pr) => (
                    <PRRow key={pr.id} pr={pr} repoId={repo.id} />
                  ))}
                </div>
              )}
              {closedPRs.length > 0 && (
                <div className="pr-section">
                  <h3 className="pr-section__title">Closed ({closedPRs.length})</h3>
                  {closedPRs.map((pr) => (
                    <PRRow key={pr.id} pr={pr} repoId={repo.id} />
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      )}

      {activeTab === "hotspots" && (
        <div className="hotspot-list">
          {hotspots.length === 0 ? (
            <div className="empty-state">No hotspot files. Sync repository history to compute risk scores.</div>
          ) : (
            <table className="hotspot-table">
              <thead>
                <tr>
                  <th>File</th>
                  <th>Risk Score</th>
                  <th>Commits (90d)</th>
                  <th>Reverts (90d)</th>
                </tr>
              </thead>
              <tbody>
                {hotspots.map((h, i) => (
                  <tr key={i}>
                    <td className="hotspot-filename">{h.filename}</td>
                    <td><RiskBar score={h.risk_score} size="sm" /></td>
                    <td>{h.commit_count_90d}</td>
                    <td className={h.revert_count_90d > 0 ? "text-warn" : ""}>{h.revert_count_90d}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}

function PRRow({ pr, repoId }: { pr: PRSummary; repoId: number }) {
  return (
    <Link
      to={`/repos/${repoId}/pull-requests/${pr.number}`}
      className="pr-row"
    >
      <div className="pr-row__left">
        <span className="pr-row__number">#{pr.number}</span>
        <div className="pr-row__info">
          <span className="pr-row__title">{pr.title}</span>
          <span className="pr-row__meta">
            {pr.author_login} &middot; {pr.state}
            {pr.draft && <span className="pr-row__draft">draft</span>}
            &middot; {pr.file_count} files &middot; +{pr.additions} / -{pr.deletions}
          </span>
        </div>
      </div>
      <div className="pr-row__right">
        <RiskBar score={pr.risk_score} size="sm" />
      </div>
    </Link>
  );
}
