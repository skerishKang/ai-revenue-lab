/**
 * #3782 — approved browser command over the EXISTING supervised Resident
 * stdin/stdout. Main-process ONLY, never renderer/preload IPC.
 *
 * The resident must first perform a genuine Broker device-authenticated,
 * per-command HUMAN P01-verified durable one-shot take. The Desktop cannot
 * invent such a grant. No product take owner is installed at present.
 */
import type { CanonicalBrowserControlCommandPort } from
  '../browser/browser-control-canonical-command-ingress.js';

export const RESIDENT_APPROVED_COMMAND_REQUEST_KIND = 'browser_control_command_take';
export const RESIDENT_APPROVED_COMMAND_CONTRACT = 'claw-browser-control-command-take.v1';
const MAX_LINE = 8_192;
const SAFE_REF = /^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}$/;

export interface ResidentApprovedBrowserCommandBoundary {
  readonly sendResidentLine: (line: string) => boolean;
  readonly takeResidentBrowserControlCommandTakeLine: () => string | null;
  readonly residentRunning: () => boolean;
}

function unavailable(): Error {
  return Object.assign(new Error('approved browser control command is unavailable'), {
    code: 'host_unavailable',
  });
}

export function createResidentApprovedBrowserControlCommandPort(input: {
  readonly boundary: ResidentApprovedBrowserCommandBoundary;
  /** FALSE until a real independently authenticated Broker/P01 source exists. */
  readonly sourceConfigured?: boolean;
  readonly timeoutMs?: number;
  readonly pollIntervalMs?: number;
  readonly sleep?: (ms: number) => Promise<void>;
}): CanonicalBrowserControlCommandPort {
  const boundary = input.boundary;
  if (!boundary ||
      typeof boundary.sendResidentLine !== 'function' ||
      typeof boundary.takeResidentBrowserControlCommandTakeLine !== 'function' ||
      typeof boundary.residentRunning !== 'function') throw unavailable();
  const configured = input.sourceConfigured === true;
  const timeoutMs = input.timeoutMs ?? 3_000;
  const pollMs = input.pollIntervalMs ?? 50;
  const sleep = input.sleep ?? ((ms: number) => new Promise<void>(resolve => setTimeout(resolve, ms)));
  const seen = new Set<string>();
  let busy = false;

  return Object.freeze({
    configured,
    async takeApprovedCommand(commandRef: string): Promise<unknown> {
      if (!configured || typeof commandRef !== 'string' ||
          !SAFE_REF.test(commandRef) || seen.has(commandRef) || busy ||
          !boundary.residentRunning()) throw unavailable();
      // Burn before crossing IPC, regardless of uncertain timeout or outcome.
      seen.add(commandRef);
      busy = true;
      try {
        const line = JSON.stringify({
          contract_version: RESIDENT_APPROVED_COMMAND_CONTRACT,
          request: RESIDENT_APPROVED_COMMAND_REQUEST_KIND,
          commandRef,
        });
        // Drop any stale one-slot response BEFORE issuing a new take. It cannot
        // become an accidental response even if commandRef is later reused.
        while (boundary.takeResidentBrowserControlCommandTakeLine() !== null) { /* discard */ }
        if (!boundary.sendResidentLine(line)) throw unavailable();
        const deadline = Date.now() + timeoutMs;
        for (;;) {
          const raw = boundary.takeResidentBrowserControlCommandTakeLine();
          if (raw !== null) {
            if (raw.length > MAX_LINE) throw unavailable();
            let answer: unknown;
            try { answer = JSON.parse(raw); } catch { throw unavailable(); }
            if (answer === null || typeof answer !== 'object' || Array.isArray(answer)) {
              throw unavailable();
            }
            const record = answer as Record<string, unknown>;
            const expected = ['event', 'contract_version', 'command_ref', 'ok', 'reason', 'command'];
            if (Object.keys(record).length !== expected.length ||
                Object.keys(record).some(key => !expected.includes(key)) ||
                record['event'] !== RESIDENT_APPROVED_COMMAND_REQUEST_KIND ||
                record['contract_version'] !== RESIDENT_APPROVED_COMMAND_CONTRACT ||
                record['command_ref'] !== commandRef ||
                record['ok'] !== true || record['reason'] !== null ||
                record['command'] === null) throw unavailable();
            // The ingress revalidates exact capability, context and action.
            return record['command'];
          }
          if (!boundary.residentRunning() || Date.now() >= deadline) throw unavailable();
          await sleep(pollMs);
        }
      } catch {
        // No untrusted resident error, action bytes, credential or P01 data.
        throw unavailable();
      } finally {
        busy = false;
      }
    },
  });
}
