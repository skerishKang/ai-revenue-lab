import { BUSINESS_GITHUB_MAP, GITHUB_REPOSITORY } from "./business-github-map.js";
import { safeError } from "./response.js";

const SCHEMA_VERSION = 1;

function iso(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

function latestIso(...values) {
  const parsed = values.map((value) => Date.parse(value || "")).filter(Number.isFinite);
  return parsed.length ? new Date(Math.max(...parsed)).toISOString() : null;
}

function normalizeIssue(issue) {
  if (!issue) return null;
  return {
    number: Number(issue.number),
    title: String(issue.title || ""),
    state: String(issue.state || "").toLowerCase(),
    updatedAt: iso(issue.updated_at),
    url: String(issue.html_url || "")
  };
}

function normalizePullRequest(pullRequest) {
  if (!pullRequest) return null;
  return {
    number: Number(pullRequest.number),
    title: String(pullRequest.title || ""),
    state: String(pullRequest.state || "").toLowerCase(),
    draft: Boolean(pullRequest.draft),
    merged: Boolean(pullRequest.merged || pullRequest.merged_at),
    headSha: String(pullRequest.head?.sha || ""),
    baseRef: String(pullRequest.base?.ref || ""),
    updatedAt: iso(pullRequest.updated_at),
    url: String(pullRequest.html_url || "")
  };
}

function safeDiagnostic(number, code, message) {
  return { businessNumber: number, code, message };
}

async function loadBusiness(mapping, client) {
  if (!mapping.repository) {
    return {
      business: {
        number: mapping.number,
        connectionState: "unmapped",
        repository: null,
        issue: null,
        pullRequest: null,
        checks: { state: "unavailable", source: "none", total: 0, completed: 0 },
        activityAt: null,
        error: null
      },
      diagnostics: []
    };
  }

  const diagnostics = [];
  let issue = null;
  let pullRequest = null;
  let checks = { state: "unavailable", source: "none", total: 0, completed: 0 };

  if (mapping.issueNumber) {
    try {
      issue = normalizeIssue(await client.getIssue(mapping.repository, mapping.issueNumber));
    } catch {
      diagnostics.push(safeDiagnostic(mapping.number, "ISSUE_UNAVAILABLE", "Mapped Issue status is unavailable."));
    }
  }

  if (mapping.pullRequestNumber) {
    try {
      pullRequest = normalizePullRequest(await client.getPullRequest(mapping.repository, mapping.pullRequestNumber));
    } catch {
      diagnostics.push(safeDiagnostic(mapping.number, "PULL_REQUEST_UNAVAILABLE", "Mapped pull request status is unavailable."));
    }
  }

  if (pullRequest?.headSha) {
    try {
      checks = await client.getChecks(mapping.repository, pullRequest.headSha);
    } catch {
      checks = { state: "unavailable", source: "pr_head", total: 0, completed: 0 };
      diagnostics.push(safeDiagnostic(mapping.number, "CHECKS_UNAVAILABLE", "Checks are unavailable for the mapped pull request."));
    }
  }

  const connectionState = diagnostics.length ? "partial" : "connected";
  const businessError = diagnostics.length
    ? { code: diagnostics[0].code, message: diagnostics[0].message }
    : null;

  return {
    business: {
      number: mapping.number,
      connectionState,
      repository: mapping.repository,
      issue,
      pullRequest,
      checks,
      activityAt: latestIso(issue?.updatedAt, pullRequest?.updatedAt),
      error: businessError
    },
    diagnostics
  };
}

export function createGitHubStatusService({
  client,
  cache,
  now = () => Date.now(),
  freshTtlSeconds = 180,
  staleTtlSeconds = 86400
}) {
  async function loadFresh() {
    const repositoryData = await client.getRepository(GITHUB_REPOSITORY);
    const defaultBranch = String(repositoryData.default_branch || "main");
    const [latestCommit, summary, businessResults] = await Promise.all([
      client.getLatestCommit(GITHUB_REPOSITORY, defaultBranch),
      client.getSummary(GITHUB_REPOSITORY),
      Promise.all(BUSINESS_GITHUB_MAP.map((mapping) => loadBusiness(mapping, client)))
    ]);
    const syncedAt = new Date(now()).toISOString();
    const errors = businessResults.flatMap((result) => result.diagnostics);
    return {
      ok: true,
      schemaVersion: SCHEMA_VERSION,
      syncedAt,
      stale: false,
      repository: {
        fullName: GITHUB_REPOSITORY,
        url: `https://github.com/${GITHUB_REPOSITORY}`,
        defaultBranch,
        latestSha: String(latestCommit.sha || ""),
        latestCommitTitle: String(latestCommit.commit?.message || "").split("\n", 1)[0],
        latestCommitAt: iso(latestCommit.commit?.committer?.date || latestCommit.commit?.author?.date)
      },
      summary: {
        openIssues: Number(summary.openIssues || 0),
        openPullRequests: Number(summary.openPullRequests || 0),
        draftPullRequests: Number(summary.draftPullRequests || 0)
      },
      businesses: businessResults.map((result) => result.business),
      errors
    };
  }

  return {
    async getStatus() {
      const cached = await cache.get();
      const ageMs = cached ? now() - cached.storedAtMs : Number.POSITIVE_INFINITY;
      if (cached && ageMs <= freshTtlSeconds * 1000) {
        return { payload: { ...cached.snapshot, stale: false }, status: 200, cacheState: "fresh" };
      }

      try {
        const snapshot = await loadFresh();
        await cache.set(snapshot);
        return { payload: snapshot, status: 200, cacheState: "miss" };
      } catch {
        if (cached && ageMs <= staleTtlSeconds * 1000) {
          const diagnostic = safeError("UPSTREAM_UNAVAILABLE", "GitHub data could not be refreshed; showing the last successful snapshot.");
          return {
            payload: {
              ...cached.snapshot,
              ok: true,
              stale: true,
              errors: [...(cached.snapshot.errors || []), diagnostic]
            },
            status: 200,
            cacheState: "stale"
          };
        }
        return {
          payload: {
            ok: false,
            schemaVersion: SCHEMA_VERSION,
            syncedAt: null,
            stale: false,
            error: safeError("UPSTREAM_UNAVAILABLE", "GitHub data is temporarily unavailable."),
            businesses: []
          },
          status: 502,
          cacheState: "unavailable"
        };
      }
    }
  };
}
