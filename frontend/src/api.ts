import axios from "axios";
import type {
  RepoSummary,
  RepoHealth,
  PRSummary,
  PRDetail,
  HotspotFile,
} from "./types";

const api = axios.create({
  baseURL: "/api",
});

api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response) {
      const status = err.response.status;
      const detail = err.response.data?.detail;
      if (status === 404) {
        throw new Error(detail || "Not found");
      }
      throw new Error(detail || `Server error (${status})`);
    }
    throw new Error("Network error - is the backend running?");
  }
);

export async function fetchRepos(): Promise<RepoSummary[]> {
  const { data } = await api.get<RepoSummary[]>("/repos");
  return data;
}

export async function fetchRepo(repoId: number): Promise<RepoSummary> {
  const { data } = await api.get<RepoSummary>(`/repos/${repoId}`);
  return data;
}

export async function fetchRepoHealth(repoId: number): Promise<RepoHealth> {
  const { data } = await api.get<RepoHealth>(`/repos/${repoId}/health`);
  return data;
}

export async function fetchRepoPRs(repoId: number): Promise<PRSummary[]> {
  const { data } = await api.get<PRSummary[]>(`/repos/${repoId}/pull-requests`);
  return data;
}

export async function fetchPRDetail(
  repoId: number,
  prNumber: number
): Promise<PRDetail> {
  const { data } = await api.get<PRDetail>(
    `/repos/${repoId}/pull-requests/${prNumber}`
  );
  return data;
}

export async function fetchHotspots(repoId: number): Promise<HotspotFile[]> {
  const { data } = await api.get<HotspotFile[]>(`/repos/${repoId}/hotspots`);
  return data;
}
