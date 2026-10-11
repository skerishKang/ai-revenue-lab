/**
 * #3583 — bounded workspace file search: scoring/ranking primitive.
 *
 * Derived from the ZCode upstream workspace file search primitive:
 *
 * ```text
 * UPSTREAM_REPO=zai-org/ZCode
 * UPSTREAM_SHA=29628c9acdb81b703bbd4080c207a0e7ce5e276e
 * UPSTREAM_PATH=packages/shared/src/workspaceFileSearch.ts
 * ADAPTATION_TYPE=DERIVED
 * ```
 *
 * Apache-2.0 upstream; attribution is preserved in the package-root
 * `THIRD_PARTY_NOTICES.md`.
 *
 * This module is pure presentation ranking: no filesystem, IPC, network or
 * provider access lives here. The caller (LocalWorkspaceController, main
 * process) performs the already-validated bounded walk inside the selected
 * root and hands over plain entries; this module only scores and ranks them.
 * Authority is unchanged — search stays a read-only listing-level surface
 * under the #1633–#1636 contract boundary (no content bytes, no absolute
 * paths in candidates, no execution of any kind).
 *
 * Adaptation deltas from upstream (documented, semantics preserved):
 * - Padiem candidates carry no absolute `path` (the renderer must never
 *   receive one), so the upstream keyword bonus is computed from the
 *   relative path only.
 * - Entry kind uses the Padiem contract union
 *   ('directory' | 'file' | 'link') instead of the upstream type.
 */
import type { WorkspaceEntry, WorkspaceEntryKind } from '../contract/ipc.js';

/**
 * Safety-net cap carried over from upstream: large enough to never feel
 * incomplete, small enough to keep ranking memory bounded for huge trees.
 */
export const WORKSPACE_FILE_SEARCH_DISPLAY_CAP = 1000;

export interface WorkspaceFileSearchCandidate {
  readonly name: string;
  readonly relativePath: string;
  readonly kind: WorkspaceEntryKind;
  /**
   * Precomputed lowercase forms (upstream trick): scoring trims+lowercases
   * once per candidate instead of per comparison, which keeps repeated
   * queries over the same walk cheap.
   */
  readonly lowercaseName: string;
  readonly lowercaseRelativePath: string;
}

export interface FilterWorkspaceFileSearchCandidatesOptions {
  readonly limit?: number;
  readonly requireQuery?: boolean;
}

export function hasWorkspaceFileSearchQuery(query: string): boolean {
  return query.trim().length > 0;
}

export function mapWorkspaceEntryToSearchCandidate(
  entry: Pick<WorkspaceEntry, 'name' | 'relativePath' | 'kind'>,
): WorkspaceFileSearchCandidate {
  const lowercaseRelativePath = entry.relativePath.trim().toLowerCase();
  return {
    name: entry.name,
    relativePath: entry.relativePath,
    kind: entry.kind,
    lowercaseName: entry.name.trim().toLowerCase(),
    lowercaseRelativePath,
  };
}

/**
 * Upstream fuzzy score (ported verbatim):
 * - empty query scores 0 (matches everything);
 * - prefix match is best, scored by remaining length (shorter remainder wins);
 * - substring beats subsequence (100 + index);
 * - otherwise a subsequence scan starts at 200 and accumulates gap penalties;
 * - `null` means no match.
 */
export function scoreWorkspaceFileFuzzyMatch(text: string, query: string): number | null {
  const normalizedText = text.trim().toLowerCase();
  const normalizedQuery = query.trim().toLowerCase();

  if (!normalizedText) {
    return null;
  }

  if (!normalizedQuery) {
    return 0;
  }

  if (normalizedText.startsWith(normalizedQuery)) {
    return normalizedText.length - normalizedQuery.length;
  }

  const substringIndex = normalizedText.indexOf(normalizedQuery);
  if (substringIndex !== -1) {
    return 100 + substringIndex;
  }

  let score = 200;
  let searchStart = 0;

  for (const char of normalizedQuery) {
    const foundIndex = normalizedText.indexOf(char, searchStart);
    if (foundIndex === -1) {
      return null;
    }

    score += foundIndex - searchStart;
    searchStart = foundIndex + 1;
  }

  return score + (normalizedText.length - normalizedQuery.length);
}

/** Same scoring on already-normalized text (upstream helper, ported). */
function scoreNormalizedFuzzyMatch(
  normalizedText: string,
  normalizedQuery: string,
): number | null {
  if (!normalizedText) {
    return null;
  }

  if (normalizedText.startsWith(normalizedQuery)) {
    return normalizedText.length - normalizedQuery.length;
  }

  const substringIndex = normalizedText.indexOf(normalizedQuery);
  if (substringIndex !== -1) {
    return 100 + substringIndex;
  }

  let score = 200;
  let searchStart = 0;

  for (const char of normalizedQuery) {
    const foundIndex = normalizedText.indexOf(char, searchStart);
    if (foundIndex === -1) {
      return null;
    }

    score += foundIndex - searchStart;
    searchStart = foundIndex + 1;
  }

  return score + (normalizedText.length - normalizedQuery.length);
}

/**
 * Candidate-level score: best of name, relative path (+25 proximity bonus,
 * upstream) and the relative-path keyword bonus (+300, upstream). Without an
 * absolute path the upstream `pathScore` leg collapses into the relative
 * path leg — documented adaptation delta.
 */
export function getWorkspaceFileSearchCandidateScore(
  candidate: WorkspaceFileSearchCandidate,
  query: string,
): number | null {
  const normalizedQuery = query.trim().toLowerCase();
  if (!normalizedQuery) {
    return 0;
  }
  const nameScore = scoreNormalizedFuzzyMatch(candidate.lowercaseName, normalizedQuery);
  const relativePathScore = scoreNormalizedFuzzyMatch(
    candidate.lowercaseRelativePath,
    normalizedQuery,
  );
  const keywordScore =
    relativePathScore !== null ? relativePathScore + 300 : Number.POSITIVE_INFINITY;
  const bestScore = Math.min(
    nameScore ?? Number.POSITIVE_INFINITY,
    relativePathScore !== null ? relativePathScore + 25 : Number.POSITIVE_INFINITY,
    keywordScore,
  );

  return Number.isFinite(bestScore) ? bestScore : null;
}

function applyWorkspaceFileSearchLimit<T>(items: T[], limit?: number): T[] {
  if (!Number.isFinite(limit)) {
    return items;
  }

  const safeLimit = Math.max(0, Math.trunc(limit ?? 0));
  return items.slice(0, safeLimit);
}

/** Upstream empty-query ordering: directories last, stable by input index. */
function getDefaultWorkspaceFileSearchPriority(candidate: WorkspaceFileSearchCandidate): number {
  return candidate.kind === 'directory' ? 1 : 0;
}

function sortDefaultWorkspaceFileSearchCandidates(
  candidates: readonly WorkspaceFileSearchCandidate[],
): WorkspaceFileSearchCandidate[] {
  return candidates
    .map((candidate, index) => ({
      candidate,
      index,
      priority: getDefaultWorkspaceFileSearchPriority(candidate),
    }))
    .sort((left, right) => left.priority - right.priority || left.index - right.index)
    .map(({ candidate }) => candidate);
}

interface ScoredWorkspaceFileSearchCandidate {
  readonly candidate: WorkspaceFileSearchCandidate;
  readonly index: number;
  readonly score: number;
}

/**
 * Upstream top-K comparator: score first, then original index (stable), then
 * name as the final deterministic tie-break.
 */
function compareScoredWorkspaceFileSearchCandidates(
  left: ScoredWorkspaceFileSearchCandidate,
  right: ScoredWorkspaceFileSearchCandidate,
): number {
  if (left.score !== right.score) {
    return left.score - right.score;
  }
  if (left.index !== right.index) {
    return left.index - right.index;
  }
  return left.candidate.name.localeCompare(right.candidate.name);
}

/**
 * Upstream binary insertion: O(n log K) top-K instead of a full sort, so a
 * 4000-entry bounded walk ranks without building a giant sorted array.
 */
function findInsertionIndexByBinarySearch(
  bestMatches: ScoredWorkspaceFileSearchCandidate[],
  scored: ScoredWorkspaceFileSearchCandidate,
): number {
  let low = 0;
  let high = bestMatches.length;
  while (low < high) {
    const mid = (low + high) >>> 1;
    const midItem = bestMatches[mid];
    if (midItem !== undefined && compareScoredWorkspaceFileSearchCandidates(scored, midItem) < 0) {
      high = mid;
    } else {
      low = mid + 1;
    }
  }
  return low === bestMatches.length ? -1 : low;
}

export function filterWorkspaceFileSearchCandidates(
  candidates: readonly WorkspaceFileSearchCandidate[],
  query: string,
  options: FilterWorkspaceFileSearchCandidatesOptions = {},
): WorkspaceFileSearchCandidate[] {
  const effectiveLimit = options.limit ?? WORKSPACE_FILE_SEARCH_DISPLAY_CAP;
  const normalizedQuery = query.trim();

  if (!normalizedQuery) {
    return options.requireQuery
      ? []
      : applyWorkspaceFileSearchLimit(
          sortDefaultWorkspaceFileSearchCandidates(candidates),
          effectiveLimit,
        );
  }

  const bestMatches: ScoredWorkspaceFileSearchCandidate[] = [];
  for (const [index, candidate] of candidates.entries()) {
    const score = getWorkspaceFileSearchCandidateScore(candidate, normalizedQuery);
    if (score === null) {
      continue;
    }

    const scored = { candidate, index, score };
    // Upstream fast path: the array is kept ordered, so its tail is the
    // current worst; a candidate that does not beat it can never qualify.
    const worst = bestMatches[bestMatches.length - 1];
    if (
      worst !== undefined &&
      bestMatches.length >= effectiveLimit &&
      compareScoredWorkspaceFileSearchCandidates(scored, worst) >= 0
    ) {
      continue;
    }

    const insertionIndex = findInsertionIndexByBinarySearch(bestMatches, scored);
    if (insertionIndex === -1) {
      if (bestMatches.length < effectiveLimit) {
        bestMatches.push(scored);
      }
      continue;
    }

    bestMatches.splice(insertionIndex, 0, scored);
    if (bestMatches.length > effectiveLimit) {
      bestMatches.pop();
    }
  }

  return bestMatches.map(({ candidate }) => candidate);
}

/**
 * Convenience wrapper for the controller: ranks already-mapped candidates and
 * returns them in ranked order. Pure — the controller owns every capability
 * boundary around it. Input/output rows carry only the contract Pick shape;
 * the controller projects metadata separately.
 */
export function searchWorkspaceEntries(
  entries: readonly WorkspaceFileSearchCandidate[],
  query: string,
  options: FilterWorkspaceFileSearchCandidatesOptions = {},
): WorkspaceFileSearchCandidate[] {
  const ranked = filterWorkspaceFileSearchCandidates(entries, query, options);
  const byRelativePath = new Map(entries.map((entry) => [entry.relativePath, entry]));
  return ranked
    .map((candidate) => byRelativePath.get(candidate.relativePath))
    .filter((candidate): candidate is WorkspaceFileSearchCandidate => candidate !== undefined);
}
