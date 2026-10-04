/**
 * #3436 — read-only result artifact presentation.
 *
 * The canonical run projection already carries each run's artifact metadata
 * (`{ documentId, filename, mediaType }`, the server's own bounded document
 * reference). This module turns that into a presentation projection and adds
 * nothing behind it:
 *
 *   SECOND_ARTIFACT_AUTHORITY=0   no artifact store, no artifact id, no
 *                                 upload/download/copy/open action. Nothing is
 *                                 fetched, resolved or interpreted — a document
 *                                 reference stays a reference and is never
 *                                 resolved into a local path.
 *   ARTIFACT_CONTENT_READ=0       file bytes are never read. A label and bounded
 *                                 metadata are all that can ever render.
 *   ARTIFACT_WRITE/DELETE/RENAME/
 *   MOVE/EXECUTE=0                the surface is a read-only list; the
 *                                 presentation carries no command at all.
 *   ARTIFACT_PATH_AUTHORITY=0     a filename is a DISPLAY LABEL, not an address.
 *                                 Anything path-shaped (absolute, traversal,
 *                                 separator-bearing) is refused, so a renderer
 *                                 can never treat it as a location.
 *
 * Fail-closed presentation: an artifact whose metadata is widened, malformed or
 * path-shaped is not rendered at all. It is counted, and the surface says
 * "unsupported result" — never a raw JSON dump of whatever the server sent.
 */

import type { CanonicalRunListItem, CanonicalRunStatus } from './canonical-run.js';

/** Human category derived from the media type prefix — never the raw value. */
export type RunArtifactKind = 'document' | 'image' | 'table' | 'archive' | 'other';

export interface RunArtifactPresentation {
  /** Stable identity for rendering: the canonical run id plus its artifact. */
  readonly key: string;
  readonly runId: string;
  readonly runStatus: CanonicalRunStatus;
  /** The run's own title, for context. Empty when the run has no title. */
  readonly runTitle: string;
  /** Safe, bounded display label. Never a path, never a ref. */
  readonly label: string;
  readonly kind: RunArtifactKind;
  /** Bounded diagnostics. Advanced-only in the UI; never a private ref. */
  readonly documentId: string;
  readonly mediaType: string;
}

export interface RunArtifactPresentationResult {
  readonly artifacts: readonly RunArtifactPresentation[];
  /** How many artifacts were refused as unsupported (malformed/path-shaped). */
  readonly unsupportedCount: number;
}

/** Bounds mirroring the canonical parser, so presentation never re-widens. */
const MAX_LABEL_LENGTH = 256;
const MAX_MEDIA_TYPE_LENGTH = 128;
const MAX_DOCUMENT_ID_LENGTH = 128;
const MAX_RUN_TITLE_LENGTH = 300;

/**
 * Fields a renderer must never render, whatever the payload says. An artifact
 * carrying one is refused outright rather than projected with the field
 * stripped — a widened canonical payload is a fail-closed answer, not a
 * cleanup job.
 */
const FORBIDDEN_ARTIFACT_FIELDS: readonly string[] = [
  'credential',
  'credential_b64',
  'session_id',
  'binding_ref',
  'actor_ref',
  'workspace_ref',
  'workspace_id',
  'token',
  'secret',
  'path',
  'absolute_path',
  'local_path',
  'url',
  'download_url',
  'provider_response',
  'raw',
];

/** A media type is `type/subtype` (RFC 6838 shape), never an address. */
const MEDIA_TYPE_SHAPE = /^[A-Za-z0-9!#$&^_.+-]+\/[A-Za-z0-9!#$&^_.+-]+$/;

/** True when the string carries a C0 control or DEL code point. */
function hasControlCharacter(value: string): boolean {
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    if (code < 32 || code === 127) return true;
  }
  return false;
}

/** Path-shaped labels are addresses, not display labels. */
function looksLikePath(value: string): boolean {
  return (
    value.includes('/') ||
    value.includes('\\') ||
    hasControlCharacter(value) ||
    value === '.' ||
    value === '..' ||
    /^[A-Za-z]:/.test(value) ||
    value.startsWith('~')
  );
}

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function boundedString(value: unknown, maximum: number): string | null {
  if (typeof value !== 'string' || value.length === 0 || value.length > maximum) return null;
  return value;
}

export function classifyRunArtifactKind(mediaType: string): RunArtifactKind {
  const normalized = mediaType.trim().toLowerCase();
  if (normalized === '') return 'other';
  if (normalized.startsWith('image/')) return 'image';
  if (
    normalized.startsWith('text/csv') ||
    normalized.startsWith('application/vnd') ||
    normalized.includes('sheet') ||
    normalized.includes('excel')
  ) {
    return 'table';
  }
  if (normalized.includes('zip') || normalized.includes('tar') || normalized.includes('compressed')) {
    return 'archive';
  }
  if (
    normalized.startsWith('text/') ||
    normalized.startsWith('application/pdf') ||
    normalized.includes('json') ||
    normalized.includes('markdown') ||
    normalized.includes('word')
  ) {
    return 'document';
  }
  return 'other';
}

/**
 * Validates one artifact into a presentation, or null when it cannot be shown.
 *
 * Refused: non-objects, widened shapes carrying a private ref or a path field,
 * missing/oversized identifiers, path-shaped or control-character labels.
 */
export function presentRunArtifact(
  run: CanonicalRunListItem,
  artifact: unknown,
): RunArtifactPresentation | null {
  if (!isPlainRecord(artifact)) return null;
  for (const forbidden of FORBIDDEN_ARTIFACT_FIELDS) {
    if (forbidden in artifact) return null;
  }
  const documentId = boundedString(artifact['documentId'], MAX_DOCUMENT_ID_LENGTH);
  const filename = boundedString(artifact['filename'], MAX_LABEL_LENGTH);
  const mediaType = boundedString(artifact['mediaType'], MAX_MEDIA_TYPE_LENGTH);
  if (documentId === null || filename === null || mediaType === null) return null;
  // Identifier and label are path-checked: a slash inside either would make it
  // an address, not a name. The media type is not path-checked — it
  // legitimately carries the `type/subtype` slash — but it IS grammar-checked
  // below, so no other shape can reach the projection as a media type.
  if (looksLikePath(documentId) || looksLikePath(filename)) return null;
  if (!MEDIA_TYPE_SHAPE.test(mediaType)) return null;

  return Object.freeze({
    key: `${run.runId}::${documentId}`,
    runId: run.runId,
    runStatus: run.status,
    runTitle: (run.title || run.action || '').slice(0, MAX_RUN_TITLE_LENGTH),
    label: filename,
    kind: classifyRunArtifactKind(mediaType),
    documentId,
    mediaType,
  });
}

/**
 * Projects every artifact of the canonical run list, preserving the canonical
 * order exactly: the projection is ordered by the server's own list, never
 * re-sorted, renamed or merged here. A run with no artifact contributes
 * nothing; an unsupported artifact is counted, never rendered.
 */
export function presentRunArtifacts(
  runs: readonly CanonicalRunListItem[] | null | undefined,
): RunArtifactPresentationResult {
  const artifacts: RunArtifactPresentation[] = [];
  let unsupportedCount = 0;
  for (const run of runs ?? []) {
    if (!isPlainRecord(run) || typeof run['runId'] !== 'string' || run['runId'] === '') {
      continue;
    }
    if (run['artifact'] === null || run['artifact'] === undefined) continue;
    const presented = presentRunArtifact(run, run['artifact']);
    if (presented === null) {
      unsupportedCount += 1;
      continue;
    }
    artifacts.push(presented);
  }
  return Object.freeze({
    artifacts: Object.freeze(artifacts),
    unsupportedCount,
  });
}

export const RUN_ARTIFACT_PRESENTATION_READ_ONLY = true;
export const ARTIFACT_CONTENT_READ = 0;
export const ARTIFACT_WRITE = 0;
export const ARTIFACT_DELETE = 0;
export const ARTIFACT_RENAME = 0;
export const ARTIFACT_MOVE = 0;
export const ARTIFACT_EXECUTE = 0;
export const SECOND_ARTIFACT_AUTHORITY = 0;
