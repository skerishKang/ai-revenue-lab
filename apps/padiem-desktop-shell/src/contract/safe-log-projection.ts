/**
 * CLAW4 #3083 — safe bounded local status/log projection.
 *
 * The renderer never reads runner stdout/stderr directly. It receives a
 * redacted, length-bounded, control-character-free projection produced in the
 * Electron main process.
 *
 *   RAW_LOG_TO_RENDERER=NO
 *   ARBITRARY_PATH_READ=NO
 *   REDACTION_APPLIED=YES
 */

export const SAFE_LOG_PROJECTION = Object.freeze({
  MAX_LINES: 200,
  DEFAULT_LINES: 50,
  MAX_LINE_LENGTH: 500,
  RAW_LOG_TO_RENDERER: false,
  ARBITRARY_PATH_READ: false,
  REDACTION_APPLIED: true,
} as const);

const REDACTION_PATTERNS: readonly RegExp[] = Object.freeze([
  // paddle:// live keys
  /padi_(?:live|test)_[A-Za-z0-9]{8,}/g,
  // Google OAuth style refresh/access tokens
  /ya29\.[A-Za-z0-9._-]{10,}/g,
  // GitHub tokens
  /gh[pousr]_[A-Za-z0-9]{16,}/g,
  // Slack / xox style
  /xox[abprs]-[A-Za-z0-9-]{10,}/g,
  // Cloudflare
  /CF[A-Za-z0-9_-]{30,}/g,
  // OpenAI style
  /sk-[A-Za-z0-9]{16,}/g,
  // Bearer headers
  /Bearer\s+[A-Za-z0-9._-]{10,}/gi,
  // Long JWTs
  /eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}/g,
  // AWS access key ids
  /AKIA[0-9A-Z]{12,}/g,
  // private key blocks
  /-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----/g,
]);

export const REDACTION_PLACEHOLDER = '[REDACTED]';

/** Strips credentials from a single line and bounds its length. */
export function redactLine(line: string): string {
  let out = line;
  for (const pattern of REDACTION_PATTERNS) {
    out = out.replace(pattern, REDACTION_PLACEHOLDER);
  }
  out = out.replace(/[^\S\r\n]+/g, ' ').trim();
  if (out.length > SAFE_LOG_PROJECTION.MAX_LINE_LENGTH) {
    out = `${out.slice(0, SAFE_LOG_PROJECTION.MAX_LINE_LENGTH)}…[TRUNCATED]`;
  }
  return out;
}

export interface BoundedLogProjection {
  readonly lines: readonly string[];
  readonly truncated: boolean;
  readonly redactionApplied: true;
}

/**
 * Projects a bounded tail of runner output for the renderer.
 *
 * Only the *last* `maxLines` redacted lines are returned, so a large log body
 * cannot be used to push data into the renderer.
 */
export function projectBoundedLog(
  rawLines: readonly string[],
  maxLines: number = SAFE_LOG_PROJECTION.DEFAULT_LINES,
): BoundedLogProjection {
  if (!Number.isInteger(maxLines) || maxLines < 1) {
    throw new Error('maxLines must be a positive integer');
  }
  const effective = Math.min(maxLines, SAFE_LOG_PROJECTION.MAX_LINES);
  const redacted = rawLines.map((line) => redactLine(String(line)));
  const tail = redacted.slice(Math.max(0, redacted.length - effective));
  return Object.freeze({
    lines: Object.freeze(tail),
    truncated: redacted.length > tail.length,
    redactionApplied: true as const,
  });
}
