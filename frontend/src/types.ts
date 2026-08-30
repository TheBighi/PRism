export interface RepoSummary {
  id: number;
  github_id: number;
  owner: string;
  name: string;
  full_name: string;
  default_branch: string | null;
  url: string;
  created_at: string | null;
  history_last_synced_at: string | null;
  pr_count: number;
  open_pr_count: number;
  avg_risk_score: number | null;
  health_score: number;
  hotspot_count: number;
}

export interface RepoHealth {
  health_score: number;
  avg_risk_score: number | null;
  total_prs: number;
  open_prs: number;
  merged_prs: number;
  failed_jobs: number;
  done_jobs: number;
  high_risk_prs: number;
  hotspot_files: HotspotFile[];
}

export interface PRSummary {
  id: number;
  github_id: number;
  number: number;
  title: string;
  state: string;
  draft: boolean;
  author_login: string;
  source_branch: string;
  target_branch: string;
  url: string;
  opened_at: string | null;
  closed_at: string | null;
  risk_score: number | null;
  job_status: string | null;
  file_count: number;
  additions: number;
  deletions: number;
}

export interface PRDetail extends PRSummary {
  body: string | null;
  head_sha: string;
  base_sha: string;
  files: PRFile[];
  jobs: AnalysisJob[];
}

export interface PRFile {
  id: number;
  filename: string;
  status: string;
  additions: number;
  deletions: number;
  changes: number;
}

export interface AnalysisJob {
  id: number;
  status: string;
  error: string | null;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  results: AnalysisResults | null;
  explanation: Explanation | null;
  explanation_status: string | null;
}

export interface AnalysisResults {
  total: number;
  breakdown: Record<string, {
    weight: number;
    contribution: number;
    score: number;
    matched_files?: string[];
  }>;
  lint?: unknown;
  security?: unknown;
  type_check?: unknown;
  dependency_diff?: unknown;
  test_results?: unknown;
  coverage?: unknown;
  diff_stats?: unknown;
}

export interface Explanation {
  summary: string;
  overall_risk: string;
  top_risks: RiskItem[];
  recommendation: {
    priority: string;
    summary: string;
    actions: string[];
  };
}

export interface RiskItem {
  title: string;
  severity: string;
  category: string;
  explanation: string;
  evidence: string;
  files: string[];
  lines: string[];
}

export interface HotspotFile {
  id?: number;
  filename: string;
  commit_count_90d: number;
  revert_count_90d: number;
  risk_score: number;
  computed_at?: string | null;
}
