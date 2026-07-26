const ALLOWLIST = ['skerishKang/ai-revenue-lab'];

function isAllowed(fullName) {
  return ALLOWLIST.includes(fullName);
}

function createClient({ fetch, getSecrets, crypto }) {
  const _fetch = fetch || globalThis.fetch;
  const _getSecrets = getSecrets;
  const _crypto = crypto || globalThis.crypto;

  async function getConfig() {
    const secrets = await _getSecrets();
    const appId = secrets.GITHUB_APP_ID;
    const installationId = secrets.GITHUB_APP_INSTALLATION_ID;
    const privateKey = secrets.GITHUB_APP_PRIVATE_KEY_PKCS8;
    if (!appId || !installationId || !privateKey) {
      const err = new Error('GitHub integration configuration is incomplete');
      err.code = 'CONFIGURATION_MISSING';
      throw err;
    }
    return { appId, installationId, privateKey };
  }

  async function getInstallationToken() {
    const { appId, installationId, privateKey } = await getConfig();
    const now = Math.floor(Date.now() / 1000);
    const payload = {
      iat: now - 60,
      exp: now + 600,
      iss: appId,
    };
    const encoder = new TextEncoder();
    const header = btoa(JSON.stringify({ alg: 'RS256', typ: 'JWT' }));
    const body = btoa(JSON.stringify(payload));
    const signingInput = `${header}.${body}`;

    const keyData = encoder.encode(privateKey);
    const key = await _crypto.subtle.importKey(
      'pkcs8',
      keyData,
      { name: 'RSASSA-PKCS1-v1_5', hash: 'SHA-256' },
      false,
      ['sign']
    );
    const signature = await _crypto.subtle.sign(
      { name: 'RSASSA-PKCS1-v1_5' },
      key,
      encoder.encode(signingInput)
    );
    const jwt = `${signingInput}.${btoa(String.fromCharCode(...new Uint8Array(signature)))}`;

    const resp = await _fetch(
      `https://api.github.com/app/installations/${installationId}/access_tokens`,
      {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${jwt}`,
          Accept: 'application/vnd.github+json',
          'User-Agent': 'portfolio-console/1.0',
        },
      }
    );

    if (!resp.ok) {
      const err = new Error('Failed to get installation token');
      err.code = 'GITHUB_AUTH_FAILED';
      err.status = resp.status;
      throw err;
    }

    const data = await resp.json();
    return data.token;
  }

  async function githubFetch(url, token) {
    const resp = await _fetch(url, {
      headers: {
        Authorization: `token ${token}`,
        Accept: 'application/vnd.github+json',
        'User-Agent': 'portfolio-console/1.0',
      },
    });
    return resp;
  }

  async function getRepo(fullName, token) {
    const resp = await githubFetch(`https://api.github.com/repos/${fullName}`, token);
    if (!resp.ok) {
      const err = new Error(`GitHub API error for repo: ${resp.status}`);
      err.code = 'GITHUB_UNAVAILABLE';
      err.status = resp.status;
      throw err;
    }
    return resp.json();
  }

  async function getLatestCommit(fullName, token) {
    const resp = await githubFetch(
      `https://api.github.com/repos/${fullName}/commits?per_page=1&sha=main`,
      token
    );
    if (!resp.ok) {
      const err = new Error(`GitHub API error for commits: ${resp.status}`);
      err.code = 'GITHUB_UNAVAILABLE';
      err.status = resp.status;
      throw err;
    }
    const commits = await resp.json();
    if (!commits.length) return null;
    return commits[0];
  }

  async function getIssues(fullName, token) {
    const resp = await githubFetch(
      `https://api.github.com/repos/${fullName}/issues?state=open&per_page=1&sort=updated&direction=desc`,
      token
    );
    if (!resp.ok) {
      const err = new Error(`GitHub API error for issues: ${resp.status}`);
      err.code = 'GITHUB_UNAVAILABLE';
      err.status = resp.status;
      throw err;
    }
    const linkHeader = resp.headers.get('Link') || '';
    const countMatch = linkHeader.match(/page=(\d+)>; rel="last"/);
    const openCount = countMatch ? parseInt(countMatch[1], 10) : 0;
    const issues = await resp.json();
    return { openCount, latest: issues.length > 0 ? issues[0] : null };
  }

  async function getPullRequests(fullName, token) {
    const resp = await githubFetch(
      `https://api.github.com/repos/${fullName}/pulls?state=open&per_page=1&sort=updated&direction=desc`,
      token
    );
    if (!resp.ok) {
      const err = new Error(`GitHub API error for PRs: ${resp.status}`);
      err.code = 'GITHUB_UNAVAILABLE';
      err.status = resp.status;
      throw err;
    }
    const linkHeader = resp.headers.get('Link') || '';
    const countMatch = linkHeader.match(/page=(\d+)>; rel="last"/);
    const openCount = countMatch ? parseInt(countMatch[1], 10) : 0;
    const prs = await resp.json();

    let draftCount = 0;
    if (prs.length > 0 && prs[0].draft) draftCount = 1;

    if (prs.length > 1) {
      draftCount = prs.filter(p => p.draft).length;
    }

    return {
      openCount,
      draftCount,
      latest: prs.length > 0 ? prs[0] : null,
      items: prs,
    };
  }

  async function getChecks(fullName, token, ref) {
    const [checksResp, statusesResp] = await Promise.all([
      githubFetch(
        `https://api.github.com/repos/${fullName}/commits/${ref}/check-runs?per_page=10`,
        token
      ),
      githubFetch(
        `https://api.github.com/repos/${fullName}/commits/${ref}/status?per_page=10`,
        token
      ),
    ]);

    let checkRuns = [];
    let statuses = [];

    if (checksResp.ok) {
      const data = await checksResp.json();
      checkRuns = data.check_runs || [];
    }

    if (statusesResp.ok) {
      const data = await statusesResp.json();
      statuses = Array.isArray(data) ? data : (data.statuses || []);
    }

    return { checkRuns, statuses };
  }

  function aggregateCIState({ checkRuns, statuses }) {
    const all = [...checkRuns, ...statuses];

    if (all.length === 0) {
      return { state: 'unavailable', source: 'none' };
    }

    const stateMap = {};
    for (const item of checkRuns) {
      stateMap[item.name || item.id] = item.conclusion || item.status;
    }
    for (const item of statuses) {
      stateMap[item.context || ''] = item.state;
    }

    const failStates = new Set([
      'failure', 'error', 'timed_out', 'cancelled', 'action_required',
      'startup_failure',
    ]);
    const pendingStates = new Set([
      'queued', 'in_progress', 'waiting', 'pending', 'expected',
    ]);
    const passStates = new Set([
      'success', 'neutral', 'skipped',
    ]);

    let hasAny = false;
    let hasFail = false;
    let hasPending = false;

    for (const state of Object.values(stateMap)) {
      if (!state || state === 'null') continue;
      hasAny = true;
      if (failStates.has(state)) hasFail = true;
      if (pendingStates.has(state)) hasPending = true;
    }

    if (!hasAny) return { state: 'unavailable', source: 'none' };

    if (hasFail) return { state: 'fail', source: checkRuns.length > 0 ? 'checks' : 'statuses' };
    if (hasPending) return { state: 'pending', source: checkRuns.length > 0 ? 'checks' : 'statuses' };
    return { state: 'pass', source: checkRuns.length > 0 ? 'checks' : 'statuses' };
  }

  function transformCommit(commitData) {
    if (!commitData) return null;
    return {
      sha: commitData.sha,
      title: (commitData.commit?.message || '').split('\n')[0],
      committedAt: commitData.commit?.committer?.date || commitData.commit?.author?.date || null,
      url: commitData.html_url || null,
    };
  }

  function transformIssue(issueData) {
    if (!issueData) return null;
    const isPR = !!(issueData.pull_request);
    if (isPR) return null;
    return {
      number: issueData.number,
      title: issueData.title,
      state: issueData.state,
      updatedAt: issueData.updated_at,
      url: issueData.html_url,
    };
  }

  function transformPullRequest(prData) {
    if (!prData) return null;
    return {
      number: prData.number,
      title: prData.title,
      state: prData.state,
      draft: !!prData.draft,
      updatedAt: prData.updated_at,
      url: prData.html_url,
    };
  }

  async function getFullStatus(fullName) {
    if (!isAllowed(fullName)) {
      const err = new Error(`Repository not allowed: ${fullName}`);
      err.code = 'INVALID_REQUEST';
      throw err;
    }

    const token = await getInstallationToken();

    const [repoData, commitData, issuesData, prsData] = await Promise.all([
      getRepo(fullName, token),
      getLatestCommit(fullName, token),
      getIssues(fullName, token),
      getPullRequests(fullName, token),
    ]);

    let ci;
    if (commitData) {
      const checks = await getChecks(fullName, token, commitData.sha);
      ci = aggregateCIState(checks);
    } else {
      ci = { state: 'unavailable', source: 'none' };
    }

    const issuesCountFromData = issuesData.openCount;
    const prCountFromData = prsData.openCount;
    const draftCountFromData = prsData.draftCount;

    return {
      fullName: repoData.full_name,
      url: repoData.html_url,
      defaultBranch: repoData.default_branch,
      latestCommit: transformCommit(commitData),
      issues: {
        openCount: issuesCountFromData,
        latest: transformIssue(issuesData.latest),
      },
      pullRequests: {
        openCount: prCountFromData,
        draftCount: draftCountFromData,
        latest: transformPullRequest(prsData.latest),
      },
      ci,
    };
  }

  return { getFullStatus, isAllowed, getConfig, getInstallationToken, getRepo, getLatestCommit, getIssues, getPullRequests, getChecks, aggregateCIState, transformCommit, transformIssue, transformPullRequest };
}

export { createClient, ALLOWLIST };
