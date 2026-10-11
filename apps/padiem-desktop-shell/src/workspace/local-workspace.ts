/**
 * #3436 — bounded local project workspace for Padiem Desktop.
 *
 * The renderer never supplies an absolute path and never receives file
 * contents. A native main-process picker selects one root; later list calls
 * accept only safe relative paths under that root. The root is a LOCAL
 * execution context only — it never becomes, replaces or writes a canonical
 * Padiem workspace (LOCAL_ROOT_IS_CANONICAL_WORKSPACE=NO), and the whole
 * surface is read-only: list and classify, nothing more.
 */
import { lstat, readdir, realpath } from 'node:fs/promises';
import path from 'node:path';

import type {
  WorkspaceListRequest,
  WorkspaceListResponse,
  WorkspaceRootResponse,
  WorkspaceSearchRequest,
  WorkspaceSearchResponse,
} from '../contract/ipc.js';
import {
  mapWorkspaceEntryToSearchCandidate,
  searchWorkspaceEntries,
} from './workspace-file-search.js';

export const MAX_WORKSPACE_ENTRIES = 200;
const MAX_RELATIVE_PATH_LENGTH = 512;
const MAX_SEGMENT_LENGTH = 255;
/**
 * #3436 project browser: navigation depth is bounded so a deep tree cannot
 * walk the renderer (or this controller) without limit. One directory at a
 * time; anything deeper fails closed with `depth_exceeded`.
 */
export const MAX_TREE_DEPTH = 24;

/**
 * #3583 workspace file search: the walk is bounded twice — by tree depth
 * (MAX_TREE_DEPTH, shared with listing) and by a total scanned-entry budget.
 * Reaching the budget stops the walk cleanly and reports `truncated` instead
 * of failing, so huge trees still return useful ranked results.
 */
export const MAX_SEARCH_ENTRIES = 4000;
/** Top-K matches returned per search; the rest stay on the caller's side. */
export const MAX_SEARCH_RESULTS = 50;
const MAX_QUERY_LENGTH = 128;

/**
 * #1635 — system/credential directories are deny-by-default in the Desktop
 * local resource layer (LocalWorkspaceController).
 *
 * These directories are never surfaced by workspace listing, never walked by
 * search, and can never be selected as a workspace root. The set mirrors the
 * Transfer Policy's credential parts (execution_target_router.py) plus the
 * commonly credential-bearing configuration directories. Deliberately
 * excluded: .git and other repository bookkeeping (workspace tools need it),
 * generic hidden dotfiles (e.g. .npmrc, .DS_Store — hidden does not mean
 * credential, and blanket dotfile denial would break normal work browsing),
 * and OS shell directories (e.g. AppData) that would over-block ordinary
 * application working directories.
 */
export const SYSTEM_CREDENTIAL_DIRECTORY_SEGMENTS: ReadonlySet<string> = new Set([
  '.ssh',
  '.aws',
  '.gnupg',
  '.azure',
  '.kube',
  '.docker',
  '.mozilla',
]);

/**
 * True when a name matches one of the credential directory segments above,
 * compared case-insensitively (Windows junctions/reparse points are
 * case-insensitive, and the same deny set must apply on POSIX mounts).
 */
export function isSystemCredentialSegment(name: string): boolean {
  return SYSTEM_CREDENTIAL_DIRECTORY_SEGMENTS.has(name.toLowerCase());
}

/**
 * True when any segment of a relative path is a credential directory.
 * Used to refuse listing into/under system/credential directories (and to
 * refuse canonical paths that resolve into them, e.g. a junction planted
 * inside a benign subdirectory).
 */
export function isSystemCredentialRelativePath(relativePath: string): boolean {
  return relativePath.split(/[\\/]+/).some(
    (segment) => segment !== '' && isSystemCredentialSegment(segment),
  );
}

export type WorkspaceRootPicker = () => Promise<string | null>;

/**
 * Injectable readdir seam (same DI pattern as the root picker). Production
 * default is `fs/promises.readdir`; tests inject a deterministic driver for
 * the post-enumeration swap race.
 */
export type WorkspaceReaddirFn = typeof readdir;

export class LocalWorkspaceController {
  #root: string | null = null;
  #readdirFn: WorkspaceReaddirFn;

  constructor(
    private readonly pickRoot: WorkspaceRootPicker,
    readdirFn: WorkspaceReaddirFn = readdir,
  ) {
    this.#readdirFn = readdirFn;
  }

  rootState(reason: WorkspaceRootResponse['reason'] = 'current'): WorkspaceRootResponse {
    if (this.#root === null) {
      return Object.freeze({
        selected: false,
        rootName: null,
        rootPath: null,
        reason,
      });
    }
    return Object.freeze({
      selected: true,
      rootName: path.basename(this.#root) || this.#root,
      rootPath: this.#root,
      reason,
    });
  }

  async chooseRoot(): Promise<WorkspaceRootResponse> {
    const selected = await this.pickRoot();
    if (selected === null) {
      return this.rootState('cancelled');
    }

    try {
      const resolved = path.resolve(selected);
      // #1635: the deny set bounds which root can be selected at all, otherwise
      // re-rooting inside a credential directory would bypass the list/search
      // deny. The helper compares whole path segments, so it reads an absolute
      // path the same way.
      if (isSystemCredentialRelativePath(resolved)) {
        return this.rootState('invalid_selection');
      }
      const canonical = await realpath(resolved);
      // The picker's own path can be a link into a credential directory, so the
      // canonical root is refused as well (same posture as listing/search).
      if (isSystemCredentialRelativePath(canonical)) {
        return this.rootState('invalid_selection');
      }
      const rootStat = await lstat(canonical);
      if (!rootStat.isDirectory()) {
        return this.rootState('invalid_selection');
      }
      this.#root = canonical;
      return this.rootState('selected');
    } catch {
      return this.rootState('invalid_selection');
    }
  }

  clearRoot(): WorkspaceRootResponse {
    this.#root = null;
    return this.rootState('cleared');
  }

  async listDirectory(request: unknown): Promise<WorkspaceListResponse> {
    if (this.#root === null) {
      return emptyListing('root_not_selected');
    }

    const parsed = parseRelativePath(request);
    if (!parsed.ok) {
      return emptyListing(parsed.errorCode, this.rootState());
    }

    const relativePath = parsed.relativePath;
    const segments = relativePath === '' ? [] : relativePath.split('/');
    if (segments.length > MAX_TREE_DEPTH) {
      return emptyListing('depth_exceeded', this.rootState(), relativePath);
    }
    // #1635 deny-by-default: never list into or under a system/credential
    // directory, even when the user-relative path must already be bounded.
    if (isSystemCredentialRelativePath(relativePath)) {
      return emptyListing('path_denied', this.rootState(), relativePath);
    }
    const candidate = path.resolve(this.#root, ...segments);
    if (!isInsideRoot(this.#root, candidate)) {
      return emptyListing('path_outside_root', this.rootState());
    }

    try {
      let walked = this.#root;
      for (const segment of segments) {
        walked = path.join(walked, segment);
        const segmentStat = await lstat(walked);
        if (segmentStat.isSymbolicLink()) {
          return emptyListing('invalid_relative_path', this.rootState(), relativePath);
        }
      }

      const candidateStat = await lstat(candidate);
      if (!candidateStat.isDirectory()) {
        return emptyListing('workspace_unavailable', this.rootState(), relativePath);
      }

      const canonicalCandidate = await realpath(candidate);
      // #1635: the canonical target may have changed after enumeration
      // (junction/symlink swap into a credential directory). Refuse the
      // request when the realpath resolves into a credential directory.
      const canonicalSegments = path
        .relative(this.#root, canonicalCandidate)
        .split(/[\\/]+/)
        .filter((segment) => segment !== '');
      if (canonicalSegments.some(isSystemCredentialSegment)) {
        return emptyListing('path_denied', this.rootState(), relativePath);
      }
      if (!isInsideRoot(this.#root, canonicalCandidate)) {
        return emptyListing('path_outside_root', this.rootState(), relativePath);
      }

      const rows = await readdir(canonicalCandidate, { withFileTypes: true });
      // #1635: credential directories never surface as entries either.
      const entries = rows
        .filter((row) => !isSystemCredentialSegment(row.name))
        .map((row) => {
          const kind = row.isDirectory()
            ? 'directory' as const
            : row.isFile()
              ? 'file' as const
              : 'link' as const;
          const childRelativePath = [...segments, row.name].join('/');
          return { name: row.name, relativePath: childRelativePath, kind };
        })
        .sort((left, right) => {
          const rank = (value: typeof left.kind): number =>
            value === 'directory' ? 0 : value === 'file' ? 1 : 2;
          const rankDifference = rank(left.kind) - rank(right.kind);
          if (rankDifference !== 0) return rankDifference;
          return left.name < right.name ? -1 : left.name > right.name ? 1 : 0;
        });

      const bounded = entries.slice(0, MAX_WORKSPACE_ENTRIES);
      const withMetadata = await Promise.all(
        bounded.map(async (entry) => {
          // Bounded basic metadata from the same validated directory: at most
          // MAX_WORKSPACE_ENTRIES stats, one directory at a time. A vanished
          // or unstat-able entry keeps its place with null metadata instead
          // of failing the whole listing.
          try {
            const stats = await lstat(path.join(canonicalCandidate, entry.name));
            return Object.freeze({
              ...entry,
              sizeBytes: stats.isFile() ? stats.size : null,
              modifiedAt: stats.mtime.toISOString(),
            });
          } catch {
            return Object.freeze({ ...entry, sizeBytes: null, modifiedAt: null });
          }
        }),
      );
      return Object.freeze({
        ok: true,
        root: this.rootState(),
        directory: relativePath,
        entries: Object.freeze(withMetadata),
        truncated: entries.length > bounded.length,
        maxEntries: MAX_WORKSPACE_ENTRIES,
        errorCode: null,
      });
    } catch {
      return emptyListing('workspace_unavailable', this.rootState(), relativePath);
    }
  }

  /**
   * #3583 — bounded fuzzy file search over the selected root.
   *
   * The renderer supplies only `{ query }`: there is no path input and no
   * absolute path anywhere in the response (matching rows reuse the same
   * relative-path-only projection as listing). The walk is main-process,
   * read-only, depth- and entry-bounded, and never follows symbolic links:
   * a link entry is skipped entirely, which both blocks traversal and keeps
   * the scan inside the user-selected root.
   */
  async search(request: unknown): Promise<WorkspaceSearchResponse> {
    if (this.#root === null) {
      return emptySearch('root_not_selected');
    }

    const query = parseSearchQuery(request);
    if (query === null) {
      return emptySearch('invalid_query', this.rootState(), '');
    }
    // Capture into a local const: async closures below cannot re-observe the
    // private field's null narrowing between awaits.
    const root: string = this.#root;

    // Walk state. Scanned entries are collected flat with their relative
    // paths; ranking happens once, after the walk, in the pure primitive.
    // Containment discipline mirrors listDirectory(): every queued directory
    // is re-canonicalized (realpath) and re-verified with isInsideRoot()
    // immediately before its readdir, so a directory swapped to a
    // symlink/junction/reparse target after enumeration can never be read
    // outside the selected root (TOCTOU containment).
    const candidates: Array<{
      readonly name: string;
      readonly relativePath: string;
      readonly kind: 'directory' | 'file';
    }> = [];
    let truncated = false;

    // Iterative BFS with explicit depth accounting. The root is depth 0 and
    // its children are depth 1, so MAX_TREE_DEPTH bounds levels below the
    // root consistently with listing. Queue items carry the parent's
    // relative segments; the joined path is re-validated before every read.
    const skipped = new Set<string>();
    const queue: Array<{
      readonly absolutePath: string;
      readonly depth: number;
      readonly segments: readonly string[];
    }> = [{ absolutePath: root, depth: 0, segments: [] }];
    try {
      while (queue.length > 0) {
        if (candidates.length >= MAX_SEARCH_ENTRIES) {
          truncated = true;
          break;
        }
        const current = queue.shift();
        if (current === undefined) break;
        // Containment re-check BEFORE reading (TOCTOU): resolve the queued
        // path through the filesystem and require it to still be a canonical
        // directory inside the selected root. A symlink swap, junction
        // replacement or reparse escape fails closed here — the directory is
        // not read and its stale enumerated candidate is dropped.
        let canonicalDir: string;
        try {
          canonicalDir = await realpath(current.absolutePath);
        } catch {
          if (current.segments.length > 0) skipped.add(current.segments.join('/'));
          continue;
        }
        if (!isInsideRoot(root, canonicalDir)) {
          if (current.segments.length > 0) skipped.add(current.segments.join('/'));
          continue;
        }
        // #1635: the canonical target may resolve to a credential directory
        // even when the traversed name was benign (e.g. a junction planted
        // inside a subdirectory to escape the walk). Refuse such a directory
        // for readahead, dropping the stale enumerated candidate.
        if (isSystemCredentialRelativePath(path.relative(root, canonicalDir))) {
          if (current.segments.length > 0) skipped.add(current.segments.join('/'));
          continue;
        }
        const dirStat = await lstat(canonicalDir);
        if (!dirStat.isDirectory()) {
          if (current.segments.length > 0) skipped.add(current.segments.join('/'));
          continue;
        }
        const rows = await this.#readdirFn(canonicalDir, { withFileTypes: true });
        for (const row of rows) {
          if (candidates.length >= MAX_SEARCH_ENTRIES) {
            truncated = true;
            break;
          }
          if (row.isSymbolicLink()) {
            // Never follow and never surface links: withFileTypes reports
            // them via lstat semantics, so a symlink/junction entry is
            // excluded from both the walk and the candidate list.
            continue;
          }
          // #1635: credential directories never surface as entries.
          if (isSystemCredentialSegment(row.name)) {
            continue;
          }
          const relativePath = [...current.segments, row.name].join('/');
          if (row.isDirectory()) {
            candidates.push({ name: row.name, relativePath, kind: 'directory' });
            if (current.depth + 1 < MAX_TREE_DEPTH) {
              queue.push({
                absolutePath: path.join(canonicalDir, row.name),
                depth: current.depth + 1,
                segments: [...current.segments, row.name],
              });
            }
          } else if (row.isFile()) {
            candidates.push({ name: row.name, relativePath, kind: 'file' });
          }
          // Anything else (reparse points not classified as plain files or
          // directories, sockets, FIFOs) is ignored.
        }
      }

      const ranked = searchWorkspaceEntries(
        candidates
          .filter((candidate) => !skipped.has(candidate.relativePath))
          .map(mapWorkspaceEntryToSearchCandidate),
        query,
        { limit: MAX_SEARCH_RESULTS },
      );

      const withMetadata = await Promise.all(
        ranked.map(async (match) => {
          try {
            // Same containment posture as listing: lstat (never follows
            // links) the addressed path. A post-enumeration swap to a link
            // simply fails this stat and the row keeps its place with null
            // metadata — nothing outside the root is ever read.
            const stats = await lstat(path.join(root, match.relativePath));
            return Object.freeze({
              name: match.name,
              relativePath: match.relativePath,
              kind: match.kind,
              sizeBytes: stats.isFile() ? stats.size : null,
              modifiedAt: stats.mtime.toISOString(),
            });
          } catch {
            return Object.freeze({
              name: match.name,
              relativePath: match.relativePath,
              kind: match.kind,
              sizeBytes: null,
              modifiedAt: null,
            });
          }
        }),
      );
      return Object.freeze({
        ok: true,
        root: this.rootState(),
        query,
        matches: Object.freeze(withMetadata),
        truncated,
        scannedEntries: candidates.length,
        maxResults: MAX_SEARCH_RESULTS,
        errorCode: null,
      });
    } catch {
      return emptySearch('workspace_unavailable', this.rootState(), query);
    }
  }
}

function parseRelativePath(
  request: unknown,
):
  | { readonly ok: true; readonly relativePath: string }
  | { readonly ok: false; readonly errorCode: 'invalid_relative_path' } {
  if (
    request !== undefined &&
    request !== null &&
    (typeof request !== 'object' || Array.isArray(request))
  ) {
    return { ok: false, errorCode: 'invalid_relative_path' };
  }
  const raw = (request ?? {}) as WorkspaceListRequest;
  const value = raw.relativePath ?? '';
  if (typeof value !== 'string' || value.length > MAX_RELATIVE_PATH_LENGTH) {
    return { ok: false, errorCode: 'invalid_relative_path' };
  }
  if (value === '') {
    return { ok: true, relativePath: '' };
  }
  if (
    value.includes('\\') ||
    value.includes('\0') ||
    value.startsWith('/') ||
    path.win32.isAbsolute(value) ||
    /^[A-Za-z]:/.test(value)
  ) {
    return { ok: false, errorCode: 'invalid_relative_path' };
  }

  const segments = value.split('/');
  if (
    segments.some(
      (segment) =>
        segment.length === 0 ||
        segment.length > MAX_SEGMENT_LENGTH ||
        segment === '.' ||
        segment === '..',
    )
  ) {
    return { ok: false, errorCode: 'invalid_relative_path' };
  }
  return { ok: true, relativePath: segments.join('/') };
}

function isInsideRoot(root: string, candidate: string): boolean {
  const relative = path.relative(root, candidate);
  return relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative));
}

/**
 * #3583 search request validation: the renderer supplies only a query
 * string. Anything that is not a plain non-empty string within the length
 * bound is refused with `invalid_query`. There is deliberately no path
 * parsing here — search has no path input at all.
 */
function parseSearchQuery(request: unknown): string | null {
  if (
    request !== undefined &&
    request !== null &&
    (typeof request !== 'object' || Array.isArray(request))
  ) {
    return null;
  }
  const raw = (request ?? {}) as WorkspaceSearchRequest;
  const value = raw.query;
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  if (trimmed.length === 0 || trimmed.length > MAX_QUERY_LENGTH) return null;
  return trimmed;
}

function emptySearch(
  errorCode: WorkspaceSearchResponse['errorCode'],
  root: WorkspaceRootResponse = Object.freeze({
    selected: false,
    rootName: null,
    rootPath: null,
    reason: 'current',
  }),
  query = '',
): WorkspaceSearchResponse {
  return Object.freeze({
    ok: false,
    root,
    query,
    matches: Object.freeze([]),
    truncated: false,
    scannedEntries: 0,
    maxResults: MAX_SEARCH_RESULTS,
    errorCode,
  });
}
function emptyListing(
  errorCode: WorkspaceListResponse['errorCode'],
  root: WorkspaceRootResponse = Object.freeze({
    selected: false,
    rootName: null,
    rootPath: null,
    reason: 'current',
  }),
  directory = '',
): WorkspaceListResponse {
  return Object.freeze({
    ok: false,
    root,
    directory,
    entries: Object.freeze([]),
    truncated: false,
    maxEntries: MAX_WORKSPACE_ENTRIES,
    errorCode,
  });
}
