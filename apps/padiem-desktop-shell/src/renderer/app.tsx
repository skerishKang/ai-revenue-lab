/**
 * CLAW4 #3083 — React renderer for the Padiem Desktop shell.
 *
 * PRESENTATION ONLY. The renderer:
 *   - cannot declare a device ONLINE
 *   - cannot approve anything (P01 stays in the runner stack)
 *   - cannot spawn a process, read a file, or reach the network
 *   - only calls the six allowlisted preload methods
 */

import { useCallback, useEffect, useState, type ReactElement } from 'react';

import { requireShellApi, RendererAuthorityError, type PadiemShellApi } from './api.js';
import type {
  BoundedLogResponse,
  DeviceLifecycleState,
  PairingDeepLinkResponse,
  RunnerHealthResponse,
  ShellStatus,
} from './types.js';

export interface ShellViewState {
  readonly status: ShellStatus | null;
  readonly health: RunnerHealthResponse | null;
  readonly pairing: PairingDeepLinkResponse | null;
  readonly log: BoundedLogResponse | null;
  readonly notice: string | null;
  readonly error: string | null;
  readonly busy: boolean;
}

export const INITIAL_SHELL_VIEW_STATE: ShellViewState = Object.freeze({
  status: null,
  health: null,
  pairing: null,
  log: null,
  notice: null,
  error: null,
  busy: false,
});

export interface ShellActions {
  readonly refresh: () => Promise<void>;
  readonly start: () => Promise<void>;
  readonly stop: () => Promise<void>;
  readonly submitPairingDeepLink: (deepLink: string) => Promise<void>;
}

export interface ShellBridge {
  readonly api: PadiemShellApi;
  readonly state: ShellViewState;
  readonly actions: ShellActions;
}

/**
 * Bridges the narrow preload API into React state.
 *
 * Exported separately so the wiring can be reasoned about (and tested) without
 * a DOM, and so every UI action is visibly an allowlisted IPC call.
 */
export function useShellBridge(): ShellBridge | { readonly error: string } {
  const [state, setState] = useState<ShellViewState>(INITIAL_SHELL_VIEW_STATE);
  const [api, setApi] = useState<PadiemShellApi | null>(null);

  useEffect(() => {
    let shellApi: PadiemShellApi;
    try {
      shellApi = requireShellApi();
    } catch (error) {
      setState((prev) => ({
        ...prev,
        error:
          error instanceof RendererAuthorityError
            ? error.message
            : 'renderer bridge unavailable',
      }));
      return;
    }
    setApi(shellApi);
  }, []);

  const refresh = useCallback(async (): Promise<void> => {
    if (!api) return;
    const [status, health, log] = await Promise.all([
      api.getStatus(),
      api.runnerHealth(),
      api.getBoundedLog(50),
    ]);
    setState((prev) => ({ ...prev, status, health, log, error: null }));
  }, [api]);

  const start = useCallback(async (): Promise<void> => {
    if (!api) return;
    setState((prev) => ({ ...prev, busy: true, error: null }));
    const result = await api.runnerStart();
    setState((prev) => ({ ...prev, busy: false, notice: result.reason }));
    await refresh();
  }, [api, refresh]);

  const stop = useCallback(async (): Promise<void> => {
    if (!api) return;
    setState((prev) => ({ ...prev, busy: true, error: null }));
    const result = await api.runnerStop();
    setState((prev) => ({ ...prev, busy: false, notice: result.reason }));
    await refresh();
  }, [api, refresh]);

  const submitPairingDeepLink = useCallback(
    async (deepLink: string): Promise<void> => {
      if (!api) return;
      const result = await api.submitPairingDeepLink(deepLink);
      setState((prev) => ({ ...prev, pairing: result }));
      await refresh();
    },
    [api, refresh],
  );

  useEffect(() => {
    if (!api) return;
    void refresh();
    const timer = setInterval(() => void refresh(), 5000);
    return () => clearInterval(timer);
  }, [api, refresh]);

  if (!api) {
    return { error: state.error ?? 'connecting to the local shell bridge…' };
  }
  return { api, state, actions: { refresh, start, stop, submitPairingDeepLink } };
}

export function DeviceStateBadge(props: { state: DeviceLifecycleState | 'UNKNOWN' }): ReactElement {
  return <span className={`state-badge state-${props.state}`}>{props.state}</span>;
}

export function StatusPanel(props: { status: ShellStatus | null }): ReactElement {
  const status = props.status;
  return (
    <section className="panel">
      <h2>Device</h2>
      <div className="row">
        <DeviceStateBadge state={status ? status.deviceState : 'UNKNOWN'} />
        <span className="subtitle">
          revision {status ? status.deviceStateRevision : 0} · canonical truth owner{' '}
          {status ? status.authoritativeTruthOwner : '#3080'}
        </span>
      </div>
    </section>
  );
}

export function RunnerPanel(props: {
  status: ShellStatus | null;
  health: RunnerHealthResponse | null;
  busy: boolean;
  actions: ShellActions;
}): ReactElement {
  const state = props.health
    ? props.health.state
    : props.status
      ? props.status.runnerState
      : 'UNKNOWN';
  return (
    <section className="panel">
      <h2>Headless runner</h2>
      <div className="row" style={{ marginBottom: 10 }}>
        <button
          className="primary"
          disabled={props.busy || state === 'RUNNING' || state === 'STARTING'}
          onClick={() => void props.actions.start()}
        >
          Start runner
        </button>
        <button
          disabled={props.busy || state === 'STOPPED'}
          onClick={() => void props.actions.stop()}
        >
          Stop runner
        </button>
        <button onClick={() => void props.actions.refresh()}>Refresh</button>
      </div>
      <dl className="facts">
        <dt>state</dt>
        <dd>{String(state)}</dd>
        <dt>pid</dt>
        <dd>{String(props.health?.pid ?? props.status?.runnerPid ?? '—')}</dd>
        <dt>process boundary</dt>
        <dd>separate headless process (renderer is not the execution authority)</dd>
        <dt>last exit code</dt>
        <dd>{String(props.health?.lastExitCode ?? '—')}</dd>
      </dl>
    </section>
  );
}

export function PairingPanel(props: { pairing: PairingDeepLinkResponse | null }): ReactElement {
  return (
    <section className="panel">
      <h2>Pairing seam</h2>
      <p className="subtitle">
        Canonical pairing and broker transport are owned by #3080. This shell only accepts a
        bounded <code>padiem://</code> seam and never stores a credential.
      </p>
      <p>{props.pairing ? props.pairing.reason : 'no deep link submitted in this session'}</p>
    </section>
  );
}

export function LogPanel(props: { log: BoundedLogResponse | null }): ReactElement {
  const lines = props.log ? props.log.lines : [];
  return (
    <section className="panel">
      <h2>Local runner log (redacted, bounded)</h2>
      <pre className="log">{lines.length === 0 ? 'no runner output yet' : lines.join('\n')}</pre>
    </section>
  );
}

export function App(): ReactElement {
  const bridge = useShellBridge();

  if ('error' in bridge) {
    return (
      <main className="shell">
        <h1>Padiem Desktop Shell — M1</h1>
        <p className="subtitle">{bridge.error}</p>
      </main>
    );
  }

  const { state, actions } = bridge;
  return (
    <main className="shell">
      <h1>Padiem Desktop Shell — M1</h1>
      <p className="subtitle">
        Electron + React presentation shell supervising a separate Padiem headless runner.
      </p>
      <StatusPanel status={state.status} />
      <RunnerPanel
        status={state.status}
        health={state.health}
        busy={state.busy}
        actions={actions}
      />
      <PairingPanel pairing={state.pairing} />
      <LogPanel log={state.log} />
      {state.notice ? <p className="notice">{state.notice}</p> : null}
      <p className="notice">
        No production signing, no auto-update rollout, no production installer publish in this
        slice.
      </p>
    </main>
  );
}
