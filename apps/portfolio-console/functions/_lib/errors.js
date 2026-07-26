const ERROR_CODES = {
  CONFIGURATION_MISSING: 'CONFIGURATION_MISSING',
  GITHUB_AUTH_FAILED: 'GITHUB_AUTH_FAILED',
  GITHUB_FORBIDDEN: 'GITHUB_FORBIDDEN',
  GITHUB_NOT_FOUND: 'GITHUB_NOT_FOUND',
  GITHUB_RATE_LIMITED: 'GITHUB_RATE_LIMITED',
  GITHUB_UNAVAILABLE: 'GITHUB_UNAVAILABLE',
  CACHE_UNAVAILABLE: 'CACHE_UNAVAILABLE',
  INVALID_REQUEST: 'INVALID_REQUEST',
};

const ERROR_MESSAGES = {
  [ERROR_CODES.CONFIGURATION_MISSING]: 'GitHub integration is not configured.',
  [ERROR_CODES.GITHUB_AUTH_FAILED]: 'GitHub authentication failed.',
  [ERROR_CODES.GITHUB_FORBIDDEN]: 'Access to GitHub data is forbidden.',
  [ERROR_CODES.GITHUB_NOT_FOUND]: 'Requested GitHub resource was not found.',
  [ERROR_CODES.GITHUB_RATE_LIMITED]: 'GitHub API rate limit exceeded.',
  [ERROR_CODES.GITHUB_UNAVAILABLE]: 'GitHub is temporarily unavailable.',
  [ERROR_CODES.CACHE_UNAVAILABLE]: 'Internal cache is unavailable.',
  [ERROR_CODES.INVALID_REQUEST]: 'Invalid request.',
};

function sanitizeError(cause) {
  if (!cause || typeof cause === 'string') {
    return {
      code: ERROR_CODES.GITHUB_UNAVAILABLE,
      message: ERROR_MESSAGES[ERROR_CODES.GITHUB_UNAVAILABLE],
    };
  }

  const code = cause.code || ERROR_CODES.GITHUB_UNAVAILABLE;
  if (!ERROR_MESSAGES[code]) {
    return {
      code: ERROR_CODES.GITHUB_UNAVAILABLE,
      message: ERROR_MESSAGES[ERROR_CODES.GITHUB_UNAVAILABLE],
    };
  }

  return {
    code,
    message: ERROR_MESSAGES[code],
  };
}

function classifyGitHubError(status, body) {
  if (status === 401 || status === 403) {
    return { code: ERROR_CODES.GITHUB_AUTH_FAILED, status: 502 };
  }
  if (status === 403) {
    return { code: ERROR_CODES.GITHUB_FORBIDDEN, status: 502 };
  }
  if (status === 404) {
    return { code: ERROR_CODES.GITHUB_NOT_FOUND, status: 502 };
  }
  if (status === 429) {
    return { code: ERROR_CODES.GITHUB_RATE_LIMITED, status: 502 };
  }
  if (status >= 500) {
    return { code: ERROR_CODES.GITHUB_UNAVAILABLE, status: 502 };
  }
  return { code: ERROR_CODES.GITHUB_UNAVAILABLE, status: 502 };
}

export { ERROR_CODES, ERROR_MESSAGES, sanitizeError, classifyGitHubError };
