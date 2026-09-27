/**
 * CLAW4 #3083 — React renderer for the Padiem Desktop shell.
 * CLAW5 #3157 — Korean/English Settings, Easy view by default.
 *
 * PRESENTATION ONLY. The renderer:
 *   - cannot declare a device ONLINE
 *   - cannot approve anything (P01 stays in the runner stack)
 *   - cannot spawn a process, read a file, or reach the network
 *   - only calls the six allowlisted preload methods
 *   - stores only a display language and a view mode, both non-sensitive
 *
 * #3157 changes what the user reads, never what the shell does: Start, Stop and
 * Refresh still call exactly the same allowlisted API methods, and the canonical
 * device state is still the connection truth the renderer reports.
 */

import { useCallback, useEffect, useMemo, useState, type ReactElement } from 'react';

import { requireShellApi, RendererAuthorityError, type PadiemShellApi } from './api.js';
import {
  SHELL_LOCALES,
  deviceStateText,
  runnerStateText,
  translate,
  type ShellLocale,
  type ShellStringKey,
} from './i18n.js';
import {
  DEFAULT_VIEW_MODE,
  SHELL_VIEW_MODES,
  createLocalPreferenceStorage,
  loadUiPreferences,
  saveUiPreferences,
  type ShellUiPreferences,
  type ShellViewMode,
} from './preferences.js';
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
  /** Which action produced `notice`. The raw reason is a diagnostic. */
  readonly noticeAction: ShellNoticeAction | null;
  readonly error: string | null;
  readonly busy: boolean;
}

/** Start or stop. Used so Easy view can say something plain about it. */
export type ShellNoticeAction = 'start' | 'stop';

export const INITIAL_SHELL_VIEW_STATE: ShellViewState = Object.freeze({
  status: null,
  health: null,
  pairing: null,
  log: null,
  notice: null,
  noticeAction: null,
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
    setState((prev) => ({ ...prev, busy: false, notice: result.reason, noticeAction: 'start' }));
    await refresh();
  }, [api, refresh]);

  const stop = useCallback(async (): Promise<void> => {
    if (!api) return;
    setState((prev) => ({ ...prev, busy: true, error: null }));
    const result = await api.runnerStop();
    setState((prev) => ({ ...prev, busy: false, notice: result.reason, noticeAction: 'stop' }));
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

export interface UiPreferencesController {
  readonly preferences: ShellUiPreferences;
  readonly setLocale: (locale: ShellLocale) => void;
  readonly setView: (view: ShellViewMode) => void;
}

/**
 * The whole of #3157's persisted state: a language and a view mode.
 *
 * Reads the host locale once on mount when nothing is stored yet, then keeps
 * every later change in the local preference store. No authority is involved.
 */
export function useUiPreferences(storage = createLocalPreferenceStorage(defaultBacking())): UiPreferencesController {
  const [preferences, setPreferences] = useState<ShellUiPreferences>(() =>
    loadUiPreferences(storage, hostLocale()),
  );
  const setLocale = useCallback(
    (locale: ShellLocale) => {
      setPreferences((prev) => {
        const next = saveUiPreferences(storage, { ...prev, locale });
        return next;
      });
    },
    [storage],
  );
  const setView = useCallback(
    (view: ShellViewMode) => {
      setPreferences((prev) => saveUiPreferences(storage, { ...prev, view }));
    },
    [storage],
  );
  return { preferences, setLocale, setView };
}

function defaultBacking():
  | { getItem(key: string): string | null; setItem(key: string, value: string): void }
  | undefined {
  const candidate = (globalThis as { localStorage?: unknown }).localStorage as
    | { getItem(key: string): string | null; setItem(key: string, value: string): void }
    | undefined;
  return candidate;
}

function hostLocale(): string | undefined {
  const candidate = (globalThis as { navigator?: { language?: unknown } }).navigator?.language;
  return typeof candidate === 'string' ? candidate : undefined;
}

export function DeviceStateBadge(props: {
  state: DeviceLifecycleState | 'UNKNOWN';
  locale: ShellLocale;
}): ReactElement {
  const { state, locale } = props;
  return (
    <span className={`state-badge state-${state}`} data-canonical-state={state}>
      {deviceStateText(locale, state)}
    </span>
  );
}

export function ConnectionPanel(props: {
  status: ShellStatus | null;
  locale: ShellLocale;
  advanced: boolean;
}): ReactElement {
  const { status, locale, advanced } = props;
  const t = (key: ShellStringKey): string => translate(locale, key);
  return (
    <section className="panel">
      <h2>{t('connection.title')}</h2>
      <div className="row">
        <DeviceStateBadge state={status ? status.deviceState : 'UNKNOWN'} locale={locale} />
        <span className="subtitle">{t('connection.explainer')}</span>
      </div>
      {advanced ? (
        <dl className="facts" data-advanced="true">
          <dt>{t('device.revision')}</dt>
          <dd>{status ? status.deviceStateRevision : 0}</dd>
          <dt>{t('device.truthOwner')}</dt>
          <dd>{status ? status.authoritativeTruthOwner : '#3080'}</dd>
        </dl>
      ) : null}
    </section>
  );
}

export function RunnerPanel(props: {
  status: ShellStatus | null;
  health: RunnerHealthResponse | null;
  busy: boolean;
  actions: ShellActions;
  locale: ShellLocale;
  advanced: boolean;
}): ReactElement {
  const { status, health, busy, actions, locale, advanced } = props;
  const t = (key: ShellStringKey): string => translate(locale, key);
  const state = health ? health.state : status ? status.runnerState : 'UNKNOWN';
  return (
    <section className="panel">
      <h2>{t('runner.title')}</h2>
      <p className="subtitle">{t('runner.explainer')}</p>
      <div className="row" style={{ marginBottom: 10 }}>
        <button
          className="primary"
          disabled={busy || state === 'RUNNING' || state === 'STARTING'}
          onClick={() => void actions.start()}
        >
          {t('runner.start')}
        </button>
        <button disabled={busy || state === 'STOPPED'} onClick={() => void actions.stop()}>
          {t('runner.stop')}
        </button>
        <button onClick={() => void actions.refresh()}>{t('runner.refresh')}</button>
      </div>
      <dl className="facts">
        <dt>{t('runner.state')}</dt>
        <dd data-canonical-state={String(state)}>{runnerStateText(locale, state)}</dd>
        {advanced ? (
          <>
            <dt>{t('runner.pid')}</dt>
            <dd>{String(health?.pid ?? status?.runnerPid ?? '—')}</dd>
            <dt>{t('runner.processBoundary')}</dt>
            <dd>separate headless process (renderer is not the execution authority)</dd>
            <dt>{t('runner.lastExitCode')}</dt>
            <dd>{String(health?.lastExitCode ?? '—')}</dd>
          </>
        ) : null}
      </dl>
    </section>
  );
}

export function PairingPanel(props: {
  pairing: PairingDeepLinkResponse | null;
  locale: ShellLocale;
  advanced: boolean;
}): ReactElement {
  const { pairing, locale, advanced } = props;
  const t = (key: ShellStringKey): string => translate(locale, key);
  return (
    <section className="panel">
      <h2>{t('pairing.title')}</h2>
      <p className="subtitle">{t('pairing.body')}</p>
      {advanced ? (
        <p data-advanced="true">
          {pairing ? pairing.reason : 'no deep link submitted in this session'}
        </p>
      ) : null}
    </section>
  );
}

export function LogPanel(props: {
  log: BoundedLogResponse | null;
  locale: ShellLocale;
  advanced: boolean;
}): ReactElement {
  const { log, locale, advanced } = props;
  const t = (key: ShellStringKey): string => translate(locale, key);
  const lines = log ? log.lines : [];
  if (!advanced) {
    return (
      <section className="panel">
        <h2>{t('log.title')}</h2>
        <p className="subtitle">{t('log.advancedOnly')}</p>
      </section>
    );
  }
  return (
    <section className="panel">
      <h2>{t('log.title')}</h2>
      <pre className="log">{lines.length === 0 ? t('log.empty') : lines.join('\n')}</pre>
    </section>
  );
}

export function SettingsPanel(props: {
  preferences: ShellUiPreferences;
  onLocale: (locale: ShellLocale) => void;
  onView: (view: ShellViewMode) => void;
  onClose: () => void;
}): ReactElement {
  const { preferences, onLocale, onView, onClose } = props;
  const t = (key: ShellStringKey): string => translate(preferences.locale, key);
  return (
    <section className="panel settings" data-view={preferences.view}>
      <h2>{t('app.settingsTitle')}</h2>
      <p className="subtitle">{t('app.settingsHint')}</p>
      <fieldset>
        <legend>{t('settings.language')}</legend>
        {SHELL_LOCALES.map((locale) => (
          <label key={locale}>
            <input
              type="radio"
              name="padiem-locale"
              value={locale}
              checked={preferences.locale === locale}
              onChange={() => onLocale(locale)}
            />
            {locale === 'ko' ? t('language.ko') : t('language.en')}
          </label>
        ))}
      </fieldset>
      <fieldset>
        <legend>{t('settings.view')}</legend>
        {SHELL_VIEW_MODES.map((view) => (
          <label key={view}>
            <input
              type="radio"
              name="padiem-view"
              value={view}
              checked={preferences.view === view}
              onChange={() => onView(view)}
            />
            {view === 'easy' ? t('settings.viewEasy') : t('settings.viewAdvanced')}
          </label>
        ))}
      </fieldset>
      <button onClick={onClose}>{t('settings.close')}</button>
    </section>
  );
}

/**
 * What a given preference set is allowed to show.
 *
 * Exported so the Easy/Advanced boundary is a value that can be tested
 * directly, instead of a set of `&&` in the components.
 */
export function visibilityFor(view: ShellViewMode): {
  readonly developerFacts: boolean;
  readonly rawPairingSeamText: boolean;
  readonly boundedLogInternals: boolean;
  readonly signingNote: boolean;
} {
  const advanced = view === 'advanced';
  return {
    developerFacts: advanced,
    rawPairingSeamText: advanced,
    boundedLogInternals: advanced,
    signingNote: advanced,
  };
}

export function ShellErrorView(props: {
  locale: ShellLocale;
  advanced: boolean;
  error: string;
  view: ShellViewMode;
}): ReactElement {
  const { locale, advanced, error, view } = props;
  return (
    <main className="shell" data-locale={locale} data-view={view}>
      <h1>{translate(locale, 'app.title')}</h1>
      {/* The raw bridge error is a diagnostic: Advanced shows it, Easy does not. */}
      <p className="subtitle">
        {advanced ? error : translate(locale, 'app.bridgeUnavailable')}
      </p>
    </main>
  );
}

export function ShellView(props: {
  state: ShellViewState;
  preferences: ShellUiPreferences;
  actions: ShellActions;
  settingsOpen: boolean;
  onToggleSettings: () => void;
  onLocale: (locale: ShellLocale) => void;
  onView: (view: ShellViewMode) => void;
  onCloseSettings: () => void;
}): ReactElement {
  const { state, preferences, actions, settingsOpen } = props;
  const locale = preferences.locale;
  const t = (key: ShellStringKey): string => translate(locale, key);
  const visibility = visibilityFor(preferences.view);
  return (
    <main className="shell" data-locale={locale} data-view={preferences.view}>
      <header className="row">
        <div>
          <h1>{t('app.title')}</h1>
          <p className="subtitle">{t('app.tagline')}</p>
        </div>
        <button className="settings-trigger" onClick={props.onToggleSettings}>
          {t('app.settings')}
        </button>
      </header>
      {settingsOpen ? (
        <SettingsPanel
          preferences={preferences}
          onLocale={props.onLocale}
          onView={props.onView}
          onClose={props.onCloseSettings}
        />
      ) : null}
      <ConnectionPanel status={state.status} locale={locale} advanced={visibility.developerFacts} />
      <RunnerPanel
        status={state.status}
        health={state.health}
        busy={state.busy}
        actions={actions}
        locale={locale}
        advanced={visibility.developerFacts}
      />
      <PairingPanel
        pairing={state.pairing}
        locale={locale}
        advanced={visibility.rawPairingSeamText}
      />
      <LogPanel log={state.log} locale={locale} advanced={visibility.boundedLogInternals} />
      {state.notice ? (
        <p className="notice">
          {/* The runner reasons are raw diagnostics ("headless runner started as
              a separate process"). Easy says the same thing plainly. */}
          {visibility.developerFacts
            ? state.notice
            : t(state.noticeAction === 'start' ? 'notice.started' : 'notice.stopped')}
        </p>
      ) : null}
      {visibility.signingNote ? <p className="notice">{t('notice.signing')}</p> : null}
    </main>
  );
}

export function App(): ReactElement {
  const bridge = useShellBridge();
  const { preferences, setLocale, setView } = useUiPreferences();
  const [settingsOpen, setSettingsOpen] = useState(false);

  if ('error' in bridge) {
    return (
      <ShellErrorView
        locale={preferences.locale}
        view={preferences.view}
        advanced={visibilityFor(preferences.view).developerFacts}
        error={bridge.error}
      />
    );
  }

  return (
    <ShellView
      state={bridge.state}
      preferences={preferences}
      actions={bridge.actions}
      settingsOpen={settingsOpen}
      onToggleSettings={() => setSettingsOpen((open) => !open)}
      onLocale={setLocale}
      onView={setView}
      onCloseSettings={() => setSettingsOpen(false)}
    />
  );
}
