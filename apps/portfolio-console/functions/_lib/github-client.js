import { assertAllowedRepository } from "./business-github-map.js";

const API_BASE = "https://api.github.com";
const API_VERSION = "2026-03-10";
const ACCEPT = "application/vnd.github+json";
const USER_AGENT = "ai-revenue-portfolio-console";

export class GitHubApiError extends Error {
  constructor(code, status, message = "GitHub data is temporarily unavailable.") {
    super(message);
    this.name = "GitHubApiError";
    this.code = code;
    this.status = status;
  }
}

function repositoryPath(repository) {
  assertAllowedRepository(repository);
  return repository.split("/").map(encodeURIComponent).join("/");
}

export function normalizeChecks(checkRuns = [], statuses = []) {
  const failConclusions = new Set(["failure", "timed_out", "cancelled", "action_required", "startup_failure"]);
  const passConclusions = new Set(["success", "neutral", "skipped"]);
  let failed = false;
  let pending = false;
  let total = 0;
  let completed = 0;

  for (const run of checkRuns || []) {
    total += 1;
    const status = String(run?.status || "").toLowerCase();
    const conclusion = String(run?.conclusion || "").toLowerCase();
    if (status !== "completed") {
      pending = true;
      continue;
    }
    completed += 1;
    if (failConclusions.has(conclusion)) failed = true;
    else if (!passConclusions.has(conclusion)) pending = true;
  }

  for (const statusItem of statuses || []) {
    total += 1;
    const state = String(statusItem?.state || "").toLowerCase();
    if (state === "failure" || state === "error") {
      failed = true;
      completed += 1;
    } else if (state === "pending" || state === "expected") {
      pending = true;
    } else if (state === "success") {
      completed += 1;
    } else {
      pending = true;
    }
  }

  const state = total === 0 ? "unavailable" : failed ? "fail" : pending ? "pending" : "pass";
  return { state, source: "pr_head", total, completed };
}

export class GitHubClient {
  constructor({ authProvider, fetchImpl = fetch }) {
    this.authProvider = authProvider;
    this.fetchImpl = fetchImpl;
  }

  async request(path, { retryAuth = true } = {}) {
    if (typeof path !== "string" || !path.startsWith("/")) {
      throw new GitHubApiError("INVALID_GITHUB_PATH", 500);
    }
    const url = new URL(path, API_BASE);
    if (url.origin !== API_BASE) throw new GitHubApiError("INVALID_GITHUB_HOST", 500);
    const token = await this.authProvider.getToken();
    const response = await this.fetchImpl(url.toString(), {
      headers: {
        Accept: ACCEPT,
        Authorization: `Bearer ${token}`,
        "X-GitHub-Api-Version": API_VERSION,
        "User-Agent": USER_AGENT
      }
    });
    if (response.status === 401 && retryAuth) {
      this.authProvider.invalidate();
      await this.authProvider.getToken({ forceRefresh: true });
      return this.request(path, { retryAuth: false });
    }
    if (!response.ok) {
      throw new GitHubApiError("GITHUB_REQUEST_FAILED", response.status);
    }
    try {
      return await response.json();
    } catch {
      throw new GitHubApiError("GITHUB_RESPONSE_INVALID", 502);
    }
  }

  async getRepository(repository) {
    return this.request(`/repos/${repositoryPath(repository)}`);
  }

  async getLatestCommit(repository, branch) {
    return this.request(`/repos/${repositoryPath(repository)}/commits/${encodeURIComponent(branch)}`);
  }

  async getIssue(repository, number) {
    return this.request(`/repos/${repositoryPath(repository)}/issues/${encodeURIComponent(String(number))}`);
  }

  async getPullRequest(repository, number) {
    return this.request(`/repos/${repositoryPath(repository)}/pulls/${encodeURIComponent(String(number))}`);
  }

  async getChecks(repository, sha) {
    const base = `/repos/${repositoryPath(repository)}/commits/${encodeURIComponent(sha)}`;
    const [runs, statuses] = await Promise.all([
      this.request(`${base}/check-runs?per_page=100`),
      this.request(`${base}/status`)
    ]);
    return normalizeChecks(runs?.check_runs || [], statuses?.statuses || []);
  }

  async getSummary(repository) {
    assertAllowedRepository(repository);
    const queries = ["is:issue is:open", "is:pr is:open", "is:pr is:open is:draft"];
    const counts = await Promise.all(queries.map((query) => {
      const q = encodeURIComponent(`repo:${repository} ${query}`);
      return this.request(`/search/issues?q=${q}&per_page=1`).then((result) => Number(result?.total_count || 0));
    }));
    return { openIssues: counts[0], openPullRequests: counts[1], draftPullRequests: counts[2] };
  }
}
