/**
 * #3436 — bounded local project workspace for Padiem Desktop.
 *
 * The renderer never supplies an absolute path and never receives file
 * contents. A native main-process picker selects one root; later list calls
 * accept only safe relative paths under that root.
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
          return Object.freeze({
            name: row.name,
            relativePath: childRelativePath,
            kind,
          });
        })
        .sort((left, right) => {
          const rank = (value: typeof left.kind): number =>
            value === 'directory' ? 0 : value === 'file' ? 1 : 2;
          const rankDifference = rank(left.kind) - rank(right.kind);
          if (rankDifference !== 0) return rankDifference;
          return left.name < right.name ? -1 : left.name > right.name ? 1 : 0;
        });

      const bounded = entries.slice(0, MAX_WORKSPACE_ENTRIES);
      return Object.freeze({
        ok: true,
        root: this.rootState(),
        directory: relativePath,
        entries: Object.freeze(bounded),
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
