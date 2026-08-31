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
      if (status === 404) throw new Error(detail || "Not found");
      throw new Error(detail || `Server error (${status})`);
    }
    throw new Error("Network error - is the backend running?");
  }
);

// Simple in-memory cache
const cache = new Map<string, { data: unknown; ts: number }>();
const CACHE_TTL = 30_000;

function cached<T>(key: string, fn: () => Promise<T>): Promise<T> {
  const hit = cache.get(key);
  if (hit && Date.now() - hit.ts < CACHE_TTL) return Promise.resolve(hit.data as T);
  return fn().then((data) => {
    cache.set(key, { data, ts: Date.now() });
    return data;
  });
}

export function invalidateCache(prefix?: string) {
  if (!prefix) { cache.clear(); return; }
  for (const k of cache.keys()) { if (k.startsWith(prefix)) cache.delete(k); }
}

export async function fetchRepos(): Promise<RepoSummary[]> {
  return cached("repos", () => api.get<RepoSummary[]>("/repos").then((r) => r.data));
}

export async function fetchRepo(repoId: number): Promise<RepoSummary> {
  return cached(`repo:${repoId}`, () => api.get<RepoSummary>(`/repos/${repoId}`).then((r) => r.data));
}

export async function fetchRepoHealth(repoId: number): Promise<RepoHealth> {
  return cached(`health:${repoId}`, () => api.get<RepoHealth>(`/repos/${repoId}/health`).then((r) => r.data));
}

export async function fetchRepoPRs(repoId: number): Promise<PRSummary[]> {
  return cached(`prs:${repoId}`, () => api.get<PRSummary[]>(`/repos/${repoId}/pull-requests`).then((r) => r.data));
}

export async function fetchRepoDetail(repoId: number) {
  return cached(`detail:${repoId}`, () =>
    api.get(`/repos/${repoId}/detail`).then((r) => r.data)
  );
}

export async function fetchPRDetail(
  repoId: number,
  prNumber: number
): Promise<PRDetail> {
  return cached(`pr:${repoId}:${prNumber}`, () =>
    api.get<PRDetail>(`/repos/${repoId}/pull-requests/${prNumber}`).then((r) => r.data)
  );
}

export async function fetchHotspots(repoId: number): Promise<HotspotFile[]> {
  return cached(`hotspots:${repoId}`, () =>
    api.get<HotspotFile[]>(`/repos/${repoId}/hotspots`).then((r) => r.data)
  );
}
