export const GITHUB_REPOSITORY = "skerishKang/ai-revenue-lab";

export const ALLOWED_REPOSITORIES = Object.freeze([GITHUB_REPOSITORY]);

export const BUSINESS_GITHUB_MAP = Object.freeze([
  { number: 1, repository: GITHUB_REPOSITORY, issueNumber: 108, pullRequestNumber: 111 },
  { number: 2, repository: GITHUB_REPOSITORY, issueNumber: 43, pullRequestNumber: 88 },
  { number: 3, repository: GITHUB_REPOSITORY, issueNumber: 55, pullRequestNumber: 85 },
  { number: 4, repository: GITHUB_REPOSITORY, issueNumber: 37, pullRequestNumber: 94 },
  { number: 5, repository: GITHUB_REPOSITORY, issueNumber: 99, pullRequestNumber: 109 },
  { number: 6, repository: GITHUB_REPOSITORY, issueNumber: 98, pullRequestNumber: null },
  { number: 7, repository: GITHUB_REPOSITORY, issueNumber: 166, pullRequestNumber: 174 },
  { number: 8, repository: GITHUB_REPOSITORY, issueNumber: 168, pullRequestNumber: 176 },
  { number: 9, repository: GITHUB_REPOSITORY, issueNumber: 170, pullRequestNumber: 175 },
  { number: 10, repository: GITHUB_REPOSITORY, issueNumber: 171, pullRequestNumber: 177 },
  { number: 11, repository: GITHUB_REPOSITORY, issueNumber: 172, pullRequestNumber: 179 },
  { number: 12, repository: GITHUB_REPOSITORY, issueNumber: 173, pullRequestNumber: 178 },
  { number: 13, repository: GITHUB_REPOSITORY, issueNumber: 76, pullRequestNumber: 78 },
  { number: 14, repository: GITHUB_REPOSITORY, issueNumber: 138, pullRequestNumber: 142 },
  { number: 15, repository: null, issueNumber: null, pullRequestNumber: null }
]);

export function assertAllowedRepository(repository) {
  if (!ALLOWED_REPOSITORIES.includes(repository)) {
    const error = new Error("Repository is not allowlisted.");
    error.code = "REPOSITORY_NOT_ALLOWED";
    throw error;
  }
  return repository;
}
