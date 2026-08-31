import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { fetchPRDetail } from "../api";
import type {
  PRDetail as PRDetailType,
  AnalysisResult,
  AnalysisFinding,
  Explanation,
} from "../types";
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
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);
    fetchPRDetail(parseInt(repoId, 10), parseInt(prNumber, 10))
      .then((data) => { if (!ctrl.signal.aborted) setPr(data); })
      .catch((err) => { if (!ctrl.signal.aborted) setError(err.message); })
      .finally(() => { if (!ctrl.signal.aborted) setLoading(false); });
    return () => ctrl.abort();
  }, [repoId, prNumber]);

  if (loading) return <Loading text="Loading pull request..." />;
  if (error)
    return (
      <div className="page">
        <div className="page-header">
          <Link to={`/repos/${repoId}`} className="back-link">
            &larr; Back to repository
          </Link>
        </div>
        <ErrorDisplay message={error} />
      </div>
    );
  if (!pr)
    return (
      <div className="page">
        <div className="page-header">
          <Link to={`/repos/${repoId}`} className="back-link">
            &larr; Back to repository
          </Link>
        </div>
        <ErrorDisplay message="Pull request not found in database" />
      </div>
    );

  const latestJob = pr.jobs[0];
  const rawResults = latestJob?.results;
  const results: AnalysisResult[] =
    Array.isArray(rawResults) ? rawResults : [];
  const rawExplanation = latestJob?.explanation;
  const explanation: Explanation | null =
    rawExplanation &&
    typeof rawExplanation === "object" &&
    !Array.isArray(rawExplanation)
      ? (rawExplanation as Explanation)
      : null;

  const byType = new Map<string, AnalysisResult>();
  for (const r of results) {
    if (r.type) byType.set(r.type, r);
  }

  const riskScore = byType.get("risk_score");
  const breakdown = riskScore?.breakdown ?? {};

  const securityFindings = byType.get("security")?.results ?? [];
  const lintFindings = byType.get("linting")?.results ?? [];
  const typeFindings = byType.get("types")?.results ?? [];
  const depChanges = byType.get("dependencies")?.results ?? [];
  const testResults = byType.get("test_results")?.results ?? [];
  const coverage = byType.get("coverage_delta")?.coverage ?? {};
  const diffStats = byType.get("diff_stats")?.stats ?? [];

  const coverageEntries = Object.entries(coverage);

  return (
    <div className="page">
      <div className="page-header">
        <Link to={`/repos/${repoId}`} className="back-link">
          &larr; Back to repository
        </Link>
        <h1>
          <a
            href={pr.url}
            target="_blank"
            rel="noopener noreferrer"
            className="pr-link"
          >
            #{pr.number} {pr.title}
          </a>
        </h1>
        <div className="pr-detail__meta">
          <span className={`state-badge state-badge--${pr.state}`}>
            {pr.state}
          </span>
          {pr.draft && (
            <span className="state-badge state-badge--draft">draft</span>
          )}
          <span>{pr.author_login}</span>
          <span>
            {pr.source_branch} &rarr; {pr.target_branch}
          </span>
          <span>
            +{pr.additions} / -{pr.deletions}
          </span>
        </div>
      </div>

      {/* LLM Explanation */}
      {explanation && (
        <div className="explanation-card">
          <div className="explanation-card__header">
            <h3>AI Analysis</h3>
            <span
              className={`risk-badge risk-badge--${explanation.overall_risk}`}
            >
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
                    <span
                      className={`severity-badge severity-badge--${risk.severity}`}
                    >
                      {risk.severity}
                    </span>
                    <strong>{risk.title}</strong>
                    <span className="risk-item__category">{risk.category}</span>
                  </div>
                  <p className="risk-item__explanation">{risk.explanation}</p>
                  {risk.files && risk.files.length > 0 && (
                    <div className="risk-item__files">
                      {risk.files.map((f, j) => (
                        <code key={j} className="risk-item__file">
                          {f}
                        </code>
                      ))}
                    </div>
                  )}
                  {risk.evidence && risk.evidence.length > 0 && (
                    <div className="risk-item__evidence">
                      {risk.evidence.map((e, j) => (
                        <div key={j} className="evidence-line">
                          {e}
                        </div>
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
              <span
                className={`priority-badge priority-badge--${explanation.recommendation.priority}`}
              >
                {explanation.recommendation.priority.replace("_", " ")}
              </span>
              <p>{explanation.recommendation.summary}</p>
              {explanation.recommendation.actions &&
                explanation.recommendation.actions.length > 0 && (
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

      {/* Risk Score Breakdown */}
      {riskScore && (
        <div className="section-card">
          <div className="section-card__header">
            <h3>Risk Score</h3>
            <span className="risk-score-total">
              {riskScore.total ?? 0}
              <span className="risk-score-total__max">/100</span>
            </span>
          </div>
          <div className="risk-score-bar-container">
            <RiskBar score={riskScore.total ?? 0} size="lg" showLabel={false} />
          </div>
          {breakdown && typeof breakdown === "object" && (
            <div className="breakdown-grid">
              {Object.entries(breakdown).map(([key, val]) => {
                const pct = val.weight > 0 ? (val.contribution / val.weight) * 100 : 0;
                return (
                  <div key={key} className="breakdown-item">
                    <div className="breakdown-item__header">
                      <span className="breakdown-item__name">
                        {key.replace(/_/g, " ")}
                      </span>
                      <span className="breakdown-item__score">
                        {val.contribution.toFixed(1)} / {val.weight}
                      </span>
                    </div>
                    <div className="breakdown-bar">
                      <div
                        className="breakdown-bar__fill"
                        style={{
                          width: `${pct}%`,
                          backgroundColor:
                            pct > 70
                              ? "var(--risk-critical)"
                              : pct > 40
                              ? "var(--risk-high)"
                              : pct > 15
                              ? "var(--risk-medium)"
                              : "var(--risk-low)",
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
                    {val.changes && val.changes.length > 0 && (
                      <div className="breakdown-item__files">
                        {val.changes.map((c, i) => (
                          <code key={i}>{c}</code>
                        ))}
                      </div>
                    )}
                    {val.failed_tests && val.failed_tests.length > 0 && (
                      <div className="breakdown-item__files">
                        {val.failed_tests.map((t, i) => (
                          <code key={i}>{t}</code>
                        ))}
                      </div>
                    )}
                    {val.security_findings != null && val.security_findings > 0 && (
                      <div className="breakdown-item__files">
                        <code>{val.security_findings} security finding{val.security_findings !== 1 ? "s" : ""}</code>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* Static Analysis Findings */}
      <StaticAnalysisSection
        title="Security Findings"
        findings={securityFindings}
        icon="S"
      />
      <StaticAnalysisSection
        title="Lint Findings"
        findings={lintFindings}
        icon="L"
      />
      <StaticAnalysisSection
        title="Type Check Findings"
        findings={typeFindings}
        icon="T"
      />

      {/* Dependency Changes */}
      {depChanges.length > 0 && (
        <div className="section-card">
          <div className="section-card__header">
            <h3>Dependency Changes</h3>
            <span className="finding-count">{depChanges.length}</span>
          </div>
          <div className="dep-list">
            {depChanges.map((f, i) => (
              <div
                key={i}
                className={`dep-item ${
                  f.message.startsWith("-") ? "dep-item--removed" : "dep-item--added"
                }`}
              >
                <span className="dep-icon">
                  {f.message.startsWith("-") ? "-" : "+"}
                </span>
                <span className="dep-message">{f.message}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Test Results */}
      {testResults.length > 0 && (
        <div className="section-card">
          <div className="section-card__header">
            <h3>Test Results</h3>
            <span className="finding-count">{testResults.length} tests</span>
          </div>
          <div className="test-list">
            {testResults.map((t, i) => (
              <div key={i} className="test-item">
                <span
                  className={`test-status ${
                    t.severity === "error"
                      ? "test-status--fail"
                      : "test-status--pass"
                  }`}
                >
                  {t.severity === "error" ? "FAIL" : "PASS"}
                </span>
                <span className="test-name">{t.filename ?? t.message}</span>
                {t.message && t.filename && (
                  <span className="test-message">{t.message}</span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Coverage Delta */}
      {coverageEntries.length > 0 && (
        <div className="section-card">
          <div className="section-card__header">
            <h3>Coverage Delta</h3>
          </div>
          <div className="coverage-list">
            {coverageEntries.map(([file, entry]) => (
              <div key={file} className="coverage-item">
                <span className="coverage-file">{file}</span>
                <div className="coverage-values">
                  {entry.base != null && (
                    <span className="coverage-val">
                      {entry.base.toFixed(1)}%
                    </span>
                  )}
                  {entry.base != null && entry.head != null && (
                    <span className="coverage-arrow">&rarr;</span>
                  )}
                  {entry.head != null && (
                    <span className="coverage-val">
                      {entry.head.toFixed(1)}%
                    </span>
                  )}
                  {entry.delta != null && (
                    <span
                      className={`coverage-delta ${
                        entry.delta >= 0
                          ? "coverage-delta--up"
                          : "coverage-delta--down"
                      }`}
                    >
                      {entry.delta >= 0 ? "+" : ""}
                      {entry.delta.toFixed(1)}pp
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Changed Files */}
      {pr.files.length > 0 && (
        <div className="section-card">
          <div className="section-card__header">
            <h3>Changed Files</h3>
            <span className="finding-count">{pr.files.length}</span>
          </div>
          <div className="file-list">
            {pr.files.map((f) => {
              const ds = diffStats.find((d) => d.filename === f.filename);
              return (
                <div key={f.id} className="file-row">
                  <span
                    className={`file-status file-status--${f.status}`}
                  >
                    {f.status[0].toUpperCase()}
                  </span>
                  <span className="file-name">{f.filename}</span>
                  <span className="file-changes">
                    <span className="text-add">
                      +{ds?.additions ?? f.additions}
                    </span>
                    <span className="text-del">
                      -{ds?.deletions ?? f.deletions}
                    </span>
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Job Status */}
      {latestJob && (
        <div className="section-card">
          <div className="section-card__header">
            <h3>Analysis Job</h3>
            <span className={`job-badge job-badge--${latestJob.status}`}>
              {latestJob.status}
            </span>
          </div>
          <div className="job-info">
            <span className="job-info__item">ID: {latestJob.id}</span>
            {latestJob.created_at && (
              <span className="job-info__item">
                Created: {new Date(latestJob.created_at).toLocaleString()}
              </span>
            )}
            {latestJob.finished_at && (
              <span className="job-info__item">
                Finished: {new Date(latestJob.finished_at).toLocaleString()}
              </span>
            )}
            {latestJob.error && (
              <span className="job-info__error">{latestJob.error}</span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function StaticAnalysisSection({
  title,
  findings,
  icon,
}: {
  title: string;
  findings: AnalysisFinding[];
  icon: string;
}) {
  if (findings.length === 0) return null;

  const bySev = (s: string) => findings.filter((f) => f.severity === s);
  const criticals = bySev("critical");
  const highs = bySev("high");
  const errors = bySev("error");
  const warnings = bySev("warning");
  const infos = bySev("info");

  return (
    <div className="section-card">
      <div className="section-card__header">
        <h3>{title}</h3>
        <div className="finding-counts">
          {criticals.length > 0 && (
            <span className="finding-count finding-count--critical">
              {criticals.length} critical
            </span>
          )}
          {highs.length > 0 && (
            <span className="finding-count finding-count--high">
              {highs.length} high
            </span>
          )}
          {errors.length > 0 && (
            <span className="finding-count finding-count--error">
              {errors.length} error{errors.length !== 1 ? "s" : ""}
            </span>
          )}
          {warnings.length > 0 && (
            <span className="finding-count finding-count--warn">
              {warnings.length} warning{warnings.length !== 1 ? "s" : ""}
            </span>
          )}
          {infos.length > 0 && (
            <span className="finding-count finding-count--info">
              {infos.length} info
            </span>
          )}
        </div>
      </div>
      <div className="finding-list">
        {findings.map((f, i) => (
          <div
            key={i}
            className={`finding-item finding-item--${f.severity}`}
          >
            <div className="finding-item__left">
              <span
                className={`severity-dot severity-dot--${f.severity}`}
              />
              <div className="finding-item__info">
                <span className="finding-item__message">{f.message}</span>
                <span className="finding-item__meta">
                  {f.filename && <span className="finding-item__file">{f.filename}{f.line != null ? `:${f.line}` : ""}</span>}
                  {f.code && <span className="finding-item__code">{f.code}</span>}
                </span>
              </div>
            </div>
            {f.suggestion && (
              <div className="finding-item__suggestion">{f.suggestion}</div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
