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
} from '../contract/ipc.js';

export const MAX_WORKSPACE_ENTRIES = 200;
const MAX_RELATIVE_PATH_LENGTH = 512;
const MAX_SEGMENT_LENGTH = 255;
/**
 * #3436 project browser: navigation depth is bounded so a deep tree cannot
 * walk the renderer (or this controller) without limit. One directory at a
 * time; anything deeper fails closed with `depth_exceeded`.
 */
export const MAX_TREE_DEPTH = 24;

export type WorkspaceRootPicker = () => Promise<string | null>;

export class LocalWorkspaceController {
  #root: string | null = null;

  constructor(private readonly pickRoot: WorkspaceRootPicker) {}

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
      const canonical = await realpath(path.resolve(selected));
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
      if (!isInsideRoot(this.#root, canonicalCandidate)) {
        return emptyListing('path_outside_root', this.rootState(), relativePath);
      }

      const rows = await readdir(canonicalCandidate, { withFileTypes: true });
      const entries = rows
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
