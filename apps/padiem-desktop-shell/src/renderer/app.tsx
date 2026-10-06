/**
 * CLAW4 #3083 — React renderer for the Padiem Desktop shell.
 * CLAW5 #3157 — Korean/English Settings, Easy view by default.
 * CLAW1 #3165 — Easy mode speaks in product language: computer connection,
 * work readiness, next action. Runner/process/log vocabulary is Advanced-only.
 *
 * PRESENTATION ONLY. The renderer:
 *   - cannot declare a device ONLINE
 *   - cannot approve anything (P01 stays in the runner stack)
 *   - cannot spawn a process, read a file, or reach the network
 *   - only calls the fixed allowlisted preload methods
 *   - stores only a display language, a theme and a view mode, all non-sensitive
 *
 * #3165 changes what the user reads and where controls sit, never what the shell
 * does: the same allowlisted API methods are called, and the canonical device
 * state is still the connection truth the renderer reports.
 */

import { useCallback, useEffect, useState, type ReactElement } from 'react';

import { requireShellApi, RendererAuthorityError, type PadiemShellApi } from './api.js';
import {
  SHELL_LOCALES,
  connectionNextActionText,
  deviceStateText,
  readinessBodyText,
  readinessStateText,
  translate,
  type ShellLocale,
  type ShellStringKey,
} from './i18n.js';
import {
  DEFAULT_VIEW_MODE,
  SHELL_THEME_PREFERENCES,
  SHELL_VIEW_MODES,
  createLocalPreferenceStorage,
  loadUiPreferences,
  resolveTheme,
  saveUiPreferences,
  type ShellThemePreference,
  type ShellUiPreferences,
  type ShellViewMode,
} from './preferences.js';
import type {
  BoundedLogResponse,
  CanonicalConversationDetail,
  CanonicalConversationListResponse,
  CanonicalRunListItem,
  CanonicalRunListResponse,
  CanonicalRunStatus,
  DeviceLifecycleState,
  PairingDeepLinkResponse,
  RunnerHealthResponse,
  ShellStatus,
  WorkspaceEntry,
  WorkspaceEntryKind,
  WorkspaceListResponse,
  WorkspaceRootResponse,
  WorkspaceSearchResponse,
} from './types.js';

export interface ShellViewState {
  readonly status: ShellStatus | null;
  readonly health: RunnerHealthResponse | null;
  readonly pairing: PairingDeepLinkResponse | null;
  readonly log: BoundedLogResponse | null;
  readonly workspaceRoot: WorkspaceRootResponse | null;
  readonly workspaceListing: WorkspaceListResponse | null;
  /** #3583 — last bounded search response; null until the first search. */
  readonly workspaceSearch: WorkspaceSearchResponse | null;
  /** #3436 project browser: the selected entry is view state, never IPC. */
  readonly selectedWorkspaceEntry: WorkspaceEntry | null;
  readonly conversationList: CanonicalConversationListResponse | null;
  readonly selectedConversation: CanonicalConversationDetail | null;
  readonly runList: CanonicalRunListResponse | null;
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
  workspaceRoot: null,
  workspaceListing: null,
  workspaceSearch: null,
  selectedWorkspaceEntry: null,
  conversationList: null,
  selectedConversation: null,
  runList: null,
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
  readonly chooseWorkspaceRoot: () => Promise<void>;
  readonly openWorkspaceDirectory: (relativePath: string) => Promise<void>;
  readonly clearWorkspaceRoot: () => Promise<void>;
  /**
   * #3583 — bounded fuzzy file search over the selected root. The renderer
   * supplies only a query string; results are a main-owned projection.
   */
  readonly searchWorkspace: (query: string) => Promise<void>;
  /**
   * #3436 project browser: selecting an entry is local view state. No IPC is
   * involved — the main process learns nothing about which entry is highlighted.
   */
  readonly selectWorkspaceEntry: (relativePath: string) => void;
  readonly selectConversation: (conversationId: string) => Promise<void>;
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

  const openWorkspaceDirectory = useCallback(
    async (relativePath: string): Promise<void> => {
      if (!api) return;
      const listing = await api.listWorkspaceDirectory(relativePath);
      setState((prev) => ({
        ...prev,
        workspaceRoot: listing.root,
        workspaceListing: listing,
        // Expanding a folder is navigation: the previous selection belonged to
        // the previous directory and is dropped rather than left ambiguous.
        selectedWorkspaceEntry: null,
      }));
    },
    [api],
  );

  const chooseWorkspaceRoot = useCallback(async (): Promise<void> => {
    if (!api) return;
    const root = await api.chooseWorkspaceRoot();
    setState((prev) => ({ ...prev, workspaceRoot: root, selectedWorkspaceEntry: null }));
    if (root.selected) {
      const listing = await api.listWorkspaceDirectory('');
      setState((prev) => ({
        ...prev,
        workspaceRoot: listing.root,
        workspaceListing: listing,
        selectedWorkspaceEntry: null,
      }));
    }
  }, [api]);

  const clearWorkspaceRoot = useCallback(async (): Promise<void> => {
    if (!api) return;
    const root = await api.clearWorkspaceRoot();
    setState((prev) => ({
      ...prev,
      workspaceRoot: root,
      workspaceListing: null,
      workspaceSearch: null,
      selectedWorkspaceEntry: null,
    }));
  }, [api]);

  const searchWorkspace = useCallback(
    async (query: string): Promise<void> => {
      if (!api) return;
      const search = await api.searchWorkspace(query);
      setState((prev) => ({ ...prev, workspaceSearch: search }));
    },
    [api],
  );

  const selectWorkspaceEntry = useCallback((relativePath: string): void => {
    setState((prev) => {
      // Only an entry of the CURRENT listing can be selected, and the entry is
      // taken from the main-owned projection rather than reconstructed here.
      const entry = prev.workspaceListing?.entries.find(
        (candidate) => candidate.relativePath === relativePath,
      );
      if (!entry) return prev;
      return { ...prev, selectedWorkspaceEntry: entry };
    });
  }, []);

  const selectConversation = useCallback(
    async (conversationId: string): Promise<void> => {
      if (!api) return;
      const result = await api.readConversation(conversationId);
      setState((prev) => ({
        ...prev,
        selectedConversation: result.ok ? result.conversation : null,
      }));
    },
    [api],
  );

  const loadRuns = useCallback(async (): Promise<void> => {
    if (!api) return;
    const runList = await api.listRuns();
    setState((prev) => ({ ...prev, runList }));
  }, [api]);

  useEffect(() => {
    if (!api) return;
    void refresh();
    void api.listWorkspaceDirectory('').then((listing) => {
      setState((prev) => ({
        ...prev,
        workspaceRoot: listing.root,
        workspaceListing: listing.ok ? listing : prev.workspaceListing,
      }));
    });
    void api.listConversations().then((conversationList) => {
      setState((prev) => ({ ...prev, conversationList }));
    });
    void loadRuns();
    const timer = setInterval(() => {
      void refresh();
      void loadRuns();
    }, 5000);
    return () => clearInterval(timer);
  }, [api, refresh, loadRuns]);

  if (!api) {
    return { error: state.error ?? 'connecting to the local shell bridge…' };
  }
  return {
    api,
    state,
    actions: {
      refresh,
      start,
      stop,
      submitPairingDeepLink,
      chooseWorkspaceRoot,
      openWorkspaceDirectory,
      clearWorkspaceRoot,
      searchWorkspace,
      selectWorkspaceEntry,
      selectConversation,
    },
  };
}

export interface UiPreferencesController {
  readonly preferences: ShellUiPreferences;
  readonly setLocale: (locale: ShellLocale) => void;
  readonly setTheme: (theme: ShellThemePreference) => void;
  readonly setView: (view: ShellViewMode) => void;
}

/**
 * The whole of #3157/#3165's persisted state: a language, a theme and a view.
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
  const setTheme = useCallback(
    (theme: ShellThemePreference) => {
      setPreferences((prev) => saveUiPreferences(storage, { ...prev, theme }));
    },
    [storage],
  );
  const setView = useCallback(
    (view: ShellViewMode) => {
      setPreferences((prev) => saveUiPreferences(storage, { ...prev, view }));
    },
    [storage],
  );
  return { preferences, setLocale, setTheme, setView };
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

/**
 * The minimal document surface the shell touches for presentation.
 *
 * Structural on purpose so a test can pass a tiny fake instead of a real DOM;
 * it only ever sets the theme attribute and the language tag.
 */
export interface AppearanceTarget {
  readonly documentElement: {
    readonly dataset: { [key: string]: string | undefined };
    lang: string;
  };
}

export function applyDocumentAppearance(
  target: AppearanceTarget,
  theme: 'light' | 'dark',
  locale: ShellLocale,
): void {
  target.documentElement.dataset['theme'] = theme;
  target.documentElement.lang = locale;
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
  busy: boolean;
  actions: ShellActions;
  locale: ShellLocale;
  advanced: boolean;
}): ReactElement {
  const { status, busy, actions, locale, advanced } = props;
  const t = (key: ShellStringKey): string => translate(locale, key);
  const state: DeviceLifecycleState | 'UNKNOWN' = status ? status.deviceState : 'UNKNOWN';
  return (
    <section className="panel">
      <h2>{t('connection.title')}</h2>
      <p className="subtitle">{t('connection.explainer')}</p>
      <div className="row">
        <DeviceStateBadge state={state} locale={locale} />
      </div>
      <p className="guidance">{connectionNextActionText(locale, state)}</p>
      <div className="row">
        <button disabled={busy} onClick={() => void actions.refresh()}>
          {t('connection.recheck')}
        </button>
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
      <h2>{t('readiness.title')}</h2>
      <p className="subtitle">{t('readiness.explainer')}</p>
      <div className="row" style={{ marginBottom: 10 }}>
        <button
          className="primary"
          disabled={busy || state === 'RUNNING' || state === 'STARTING'}
          onClick={() => void actions.start()}
        >
          {t('readiness.start')}
        </button>
        <button disabled={busy || state === 'STOPPED'} onClick={() => void actions.stop()}>
          {t('readiness.pause')}
        </button>
      </div>
      <div className="row">
        <span className="state-badge state-readiness" data-canonical-state={String(state)}>
          {readinessStateText(locale, state)}
        </span>
      </div>
      <p className="guidance">{readinessBodyText(locale, state)}</p>
      {advanced ? (
        <dl className="facts" data-advanced="true">
          <dt>{t('readiness.pid')}</dt>
          <dd>{String(health?.pid ?? status?.runnerPid ?? '-')}</dd>
          <dt>{t('readiness.processBoundary')}</dt>
          <dd>{t('readiness.processBoundaryValue')}</dd>
          <dt>{t('readiness.lastExitCode')}</dt>
          <dd>{String(health?.lastExitCode ?? '-')}</dd>
        </dl>
      ) : null}
    </section>
  );
}

function parentWorkspacePath(relativePath: string): string {
  const parts = relativePath.split('/').filter(Boolean);
  parts.pop();
  return parts.join('/');
}

function workspaceBreadcrumbs(rootName: string, relativePath: string): readonly string[] {
  const segments = relativePath.split('/').filter(Boolean);
  return [rootName, ...segments];
}

/** Closed map from the main-owned entry kind to its localized label. */
const WORKSPACE_KIND_LABEL: Record<WorkspaceEntryKind, ShellStringKey> = {
  directory: 'workspace.kind.directory',
  file: 'workspace.kind.file',
  link: 'workspace.kind.link',
};

/** Human-readable byte size for the entry list. Bounded, never loads content. */
function formatWorkspaceSize(sizeBytes: number | null, locale: ShellLocale): string {
  if (sizeBytes === null || !Number.isFinite(sizeBytes) || sizeBytes < 0) return '';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = sizeBytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value = value / 1024;
    unit += 1;
  }
  const rendered = unit === 0 ? String(Math.round(value)) : value.toFixed(1);
  return `${rendered} ${units[unit]}`;
}

/** The selected entry's modified date, localized, or a plain dash. */
function formatWorkspaceModified(modifiedAt: string | null, locale: ShellLocale): string {
  if (modifiedAt === null) return '-';
  const parsed = Date.parse(modifiedAt);
  if (!Number.isFinite(parsed)) return '-';
  return new Date(parsed).toLocaleString(locale === 'ko' ? 'ko-KR' : 'en-US');
}

/**
 * #3436 project browser.
 *
 * Read-only, one directory at a time: the main process owns the selected root
 * and answers only root-relative list requests, so the renderer can expand a
 * folder but can never address an absolute path. Selecting an entry is local
 * view state — no write, rename, delete or create control exists anywhere on
 * this surface (LOCAL_FILE_BROWSER_READ_ONLY=YES).
 */
export function WorkspacePanel(props: {
  root: WorkspaceRootResponse | null;
  listing: WorkspaceListResponse | null;
  /** #3583 — last bounded search response; null until the first search. */
  search: WorkspaceSearchResponse | null;
  selectedEntry: WorkspaceEntry | null;
  actions: ShellActions;
  locale: ShellLocale;
  advanced: boolean;
}): ReactElement {
  const { root, listing, search, selectedEntry, actions, locale, advanced } = props;
  const t = (key: ShellStringKey): string => translate(locale, key);
  const selected = root?.selected === true;
  const directory = listing?.directory ?? '';
  const crumbs = workspaceBreadcrumbs(root?.rootName ?? '', directory);
  /** While a query is active the search projection replaces the listing. */
  const searchActive = search !== null && search.query.trim() !== '';

  return (
    <section className="panel workspace-panel">
      <div className="workspace-heading">
        <div>
          <h2>{t('workspace.title')}</h2>
          <p className="subtitle">{t('workspace.explainer')}</p>
        </div>
        <div className="row">
          <button className={selected ? '' : 'primary'} onClick={() => void actions.chooseWorkspaceRoot()}>
            {selected ? t('workspace.change') : t('workspace.choose')}
          </button>
          {selected ? (
            <button onClick={() => void actions.clearWorkspaceRoot()}>{t('workspace.clear')}</button>
          ) : null}
        </div>
      </div>

      {!selected ? <p className="guidance">{t('workspace.empty')}</p> : null}

      {selected ? (
        <>
          <nav className="workspace-breadcrumb" aria-label={t('workspace.breadcrumb')}>
            {crumbs.map((crumb, index) => {
              const isLast = index === crumbs.length - 1;
              const target = crumbs.slice(1, index).join('/');
              return isLast ? (
                <span key={`${crumb}-${index}`} className="workspace-crumb workspace-crumb-current" aria-current="location">
                  {crumb}
                </span>
              ) : (
                <button
                  key={`${crumb}-${index}`}
                  className="workspace-crumb"
                  onClick={() => void actions.openWorkspaceDirectory(target)}
                >
                  {crumb}
                </button>
              );
            })}
          </nav>
          {advanced && root?.rootPath ? (
            <p className="workspace-path" data-advanced="true">{root.rootPath}</p>
          ) : null}
          {/* The local root is a local execution context, not a workspace:
              saying so here keeps the two concepts from being conflated. */}
          <p className="workspace-local-note">{t('workspace.localOnlyNote')}</p>
          <div className="row workspace-nav">
            <button disabled={directory === ''} onClick={() => void actions.openWorkspaceDirectory(parentWorkspacePath(directory))}>
              {t('workspace.up')}
            </button>
            <button disabled={directory === ''} onClick={() => void actions.openWorkspaceDirectory('')}>
              {t('workspace.root')}
            </button>
          </div>
          {/* #3583 — bounded file search. The form submits ONLY a query
              string; there is no path input anywhere on this surface. */}
          <form
            className="workspace-search"
            data-search-active={searchActive ? 'true' : 'false'}
            onSubmit={(event) => {
              event.preventDefault();
              const value = new FormData(event.currentTarget).get('query');
              if (typeof value === 'string') void actions.searchWorkspace(value);
            }}
            onReset={() => void actions.searchWorkspace('')}
          >
            <label className="workspace-search-label" htmlFor="workspace-search-input">
              {t('workspace.searchLabel')}
            </label>
            <input
              id="workspace-search-input"
              name="query"
              type="search"
              maxLength={128}
              placeholder={t('workspace.searchPlaceholder')}
              disabled={!selected}
            />
          </form>
          {searchActive && search && !search.ok ? (
            <p className="workspace-error" data-error-code={search.errorCode ?? 'none'}>
              {search.errorCode === 'invalid_query'
                ? t('workspace.searchNoMatches')
                : t('workspace.unavailable')}
            </p>
          ) : null}
          {searchActive && search?.ok ? (
            <ul className="workspace-list workspace-search-results" data-search-results="true">
              {search.matches.map((entry) => (
                <li
                  key={entry.relativePath}
                  data-kind={entry.kind}
                  data-entry-path={entry.relativePath}
                >
                  {entry.kind === 'directory' ? (
                    <button
                      className="workspace-entry"
                      onClick={() => {
                        void actions.openWorkspaceDirectory(entry.relativePath);
                        void actions.searchWorkspace('');
                      }}
                    >
                      <span aria-hidden="true">▸</span>
                      <span>{entry.name}</span>
                      <span className="workspace-entry-size">{entry.relativePath}</span>
                    </button>
                  ) : (
                    <button className="workspace-entry workspace-entry-selectable">
                      <span aria-hidden="true">{entry.kind === 'file' ? '·' : '↗'}</span>
                      <span>{entry.name}</span>
                      <span className="workspace-entry-size">{entry.relativePath}</span>
                    </button>
                  )}
                </li>
              ))}
            </ul>
          ) : null}
          {searchActive && search?.ok && search.matches.length === 0 ? (
            <p className="guidance" data-search-empty="true">
              {t('workspace.searchNoMatches')}
            </p>
          ) : null}
          {searchActive && search?.ok && (search.truncated || search.matches.length >= search.maxResults) ? (
            <p className="notice" data-search-truncated="true">
              {t('workspace.searchTruncated')}
            </p>
          ) : null}
          {!searchActive ? (
            <>
          {listing && !listing.ok ? (
            <p className="workspace-error" data-error-code={listing.errorCode ?? 'none'}>
              {listing.errorCode === 'depth_exceeded'
                ? t('workspace.depthExceeded')
                : t('workspace.unavailable')}
            </p>
          ) : null}
          <ul className="workspace-list">
            {(listing?.entries ?? []).map((entry) => {
              const isSelected = selectedEntry?.relativePath === entry.relativePath;
              const size = formatWorkspaceSize(entry.sizeBytes, locale);
              return (
                <li
                  key={entry.relativePath}
                  data-kind={entry.kind}
                  data-entry-path={entry.relativePath}
                  data-selected={isSelected ? 'true' : 'false'}
                >
                  {entry.kind === 'directory' ? (
                    <button className="workspace-entry" onClick={() => void actions.openWorkspaceDirectory(entry.relativePath)}>
                      <span aria-hidden="true">▸</span>
                      <span>{entry.name}</span>
                    </button>
                  ) : (
                    <button
                      className={`workspace-entry workspace-entry-selectable${isSelected ? ' workspace-entry-selected' : ''}`}
                      aria-pressed={isSelected}
                      onClick={() => actions.selectWorkspaceEntry(entry.relativePath)}
                    >
                      <span aria-hidden="true">{entry.kind === 'file' ? '·' : '↗'}</span>
                      <span>{entry.name}</span>
                      {size ? <span className="workspace-entry-size">{size}</span> : null}
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
          {listing?.ok && listing.entries.length === 0 ? (
            <p className="guidance">{t('workspace.noEntries')}</p>
          ) : null}
          {listing?.truncated ? <p className="notice">{t('workspace.truncated')}</p> : null}
            </>
          ) : null}
          {selectedEntry ? (
            <div className="workspace-selection" data-selected-path={selectedEntry.relativePath}>
              <strong>{selectedEntry.name}</strong>
              <dl>
                <dt>{t('workspace.selectedKind')}</dt>
                <dd>{t(WORKSPACE_KIND_LABEL[selectedEntry.kind])}</dd>
                <dt>{t('workspace.selectedPath')}</dt>
                <dd>{selectedEntry.relativePath}</dd>
                <dt>{t('workspace.selectedSize')}</dt>
                <dd>{formatWorkspaceSize(selectedEntry.sizeBytes, locale) || '-'}</dd>
                <dt>{t('workspace.selectedModified')}</dt>
                <dd>{formatWorkspaceModified(selectedEntry.modifiedAt, locale)}</dd>
              </dl>
            </div>
          ) : null}
        </>
      ) : null}
    </section>
  );
}

/**
 * B2a/B2b conversation workspace surface.
 *
 * This is deliberately a fail-closed presentation surface. It renders no
 * composer and no local transcript: what it shows is a projection of the
 * canonical Padiem conversation authority (apps/padiem-chat /api/conversations)
 * fetched through the main-owned bounded client. The Desktop mints no
 * conversation id and keeps no conversation store — if the canonical source is
 * unavailable or a payload is malformed, the surface stays at
 * `data-conversation-source="canonical-required"` instead of substituting a
 * temporary desktop conversation.
 */
export function ConversationWorkspacePanel(props: {
  locale: ShellLocale;
  advanced: boolean;
  conversations: CanonicalConversationListResponse | null;
  selectedConversation: CanonicalConversationDetail | null;
  onSelectConversation: (conversationId: string) => void;
}): ReactElement {
  const { locale, advanced, conversations, selectedConversation } = props;
  const t = (key: ShellStringKey): string => translate(locale, key);
  const canonical = conversations !== null && conversations.ok;
  const source = canonical ? 'canonical' : 'canonical-required';
  return (
    <section
      className="conversation-workspace"
      data-conversation-source={source}
      aria-labelledby="desktop-conversation-title"
    >
      <div className="conversation-workspace-header">
        <h2 id="desktop-conversation-title">{t('desktop.conversationTitle')}</h2>
        <span className="conversation-source-dot" aria-hidden="true" />
      </div>
      {canonical && conversations.conversations.length > 0 ? (
        <div className="conversation-canonical-body">
          <nav className="conversation-list" aria-label={t('desktop.conversationListLabel')}>
            {conversations.conversations.map((item) => (
              <button
                key={item.id}
                type="button"
                className={
                  selectedConversation?.id === item.id
                    ? 'conversation-list-entry selected'
                    : 'conversation-list-entry'
                }
                data-conversation-id={item.id}
                onClick={() => props.onSelectConversation(item.id)}
              >
                {item.title || t('desktop.conversationUntitled')}
              </button>
            ))}
          </nav>
          <div className="conversation-transcript">
            {selectedConversation === null ? (
              <p className="conversation-transcript-note">{t('desktop.conversationSelectHint')}</p>
            ) : (
              selectedConversation.messages.map((message, index) => (
                <article
                  key={`${selectedConversation.id}-${index}`}
                  className="conversation-message"
                  data-role={message.role}
                >
                  <p>{message.content}</p>
                </article>
              ))
            )}
          </div>
        </div>
      ) : (
        <div className="conversation-empty-state">
          <div className="conversation-mark" aria-hidden="true">P</div>
          <h3>{t('desktop.conversationPendingTitle')}</h3>
          <p>{t('desktop.conversationPendingBody')}</p>
          {advanced ? (
            <p className="conversation-authority-note" data-advanced="true">
              {t('desktop.conversationAuthorityNote')}
            </p>
          ) : null}
        </div>
      )}
      {advanced ? (
        <p className="conversation-authority-note" data-advanced="true">
          {t('desktop.conversationAuthorityNote')}
        </p>
      ) : null}
    </section>
  );
}

/**
 * #3436 B3a — canonical run activity surface.
 *
 * A fail-closed presentation of the canonical Padiem Claw run history
 * (apps/padiem-chat /api/claw/runs), the same authority Web Claw reads. The
 * Desktop mints no run id, keeps no run store and offers no mutation: what is
 * shown is the server's own bounded projection of the owner's recent runs.
 * When the canonical source is unavailable the surface stays at
 * `data-run-source="canonical-required"` — never a local run list.
 *
 * `liveActivitySource` is projected honestly: the repository has no live
 * run-event authority yet, so this is a bounded recent-records view, and it is
 * never presented as a live feed.
 */
export function RunActivityPanel(props: {
  locale: ShellLocale;
  advanced: boolean;
  runs: CanonicalRunListResponse | null;
}): ReactElement {
  const { locale, advanced, runs } = props;
  const t = (key: ShellStringKey): string => translate(locale, key);
  const canonical = runs !== null && runs.ok;
  const source = canonical ? 'canonical' : 'canonical-required';
  return (
    <section className="run-activity" data-run-source={source} aria-labelledby="desktop-run-title">
      <div className="run-activity-header">
        <h2 id="desktop-run-title">{t('desktop.runTitle')}</h2>
        <span className="run-source-dot" aria-hidden="true" />
      </div>
      {canonical && runs.runs.length > 0 ? (
        <ul className="run-list">
          {runs.runs.map((run) => (
            <RunActivityEntry key={run.runId} run={run} locale={locale} advanced={advanced} />
          ))}
        </ul>
      ) : canonical ? (
        <p className="run-empty-state">{t('desktop.runEmpty')}</p>
      ) : (
        <div className="run-empty-state run-pending">
          <h3>{t('desktop.runPendingTitle')}</h3>
          <p>{t('desktop.runPendingBody')}</p>
        </div>
      )}
      {advanced ? (
        <p className="run-authority-note" data-advanced="true">
          {t('desktop.runAuthorityNote')}
        </p>
      ) : null}
    </section>
  );
}

function runStatusText(locale: ShellLocale, status: CanonicalRunStatus): string {
  const key = (
    {
      queued: 'desktop.runStatusQueued',
      preparing: 'desktop.runStatusPreparing',
      running: 'desktop.runStatusRunning',
      waiting_approval: 'desktop.runStatusWaitingApproval',
      completed: 'desktop.runStatusCompleted',
      failed: 'desktop.runStatusFailed',
      cancelled: 'desktop.runStatusCancelled',
    } as const
  )[status];
  return translate(locale, key);
}

/**
 * One canonical run row. Every field is the server's own: the linked
 * conversation and workspace ids are projected verbatim and never re-derived
 * from the Desktop's local state. Canonical ids stay Advanced-only (#3165).
 */
function RunActivityEntry(props: {
  run: CanonicalRunListItem;
  locale: ShellLocale;
  advanced: boolean;
}): ReactElement {
  const { run, locale, advanced } = props;
  const t = (key: ShellStringKey): string => translate(locale, key);
  return (
    <li className="run-entry" data-run-status={run.status}>
      <div className="run-entry-main">
        <span className={`run-status-badge status-${run.status}`}>
          {runStatusText(locale, run.status)}
        </span>
        <span className="run-title">{run.title || run.action || t('desktop.runEmpty')}</span>
      </div>
      {run.resultSummary ? <p className="run-result">{run.resultSummary}</p> : null}
      <div className="run-entry-facts">
        {run.artifact !== null ? <span className="run-chip">{t('desktop.runArtifact')}</span> : null}
        {run.conversationId !== null ? (
          <span className="run-chip">{t('desktop.runConversationLinked')}</span>
        ) : null}
      </div>
      {advanced ? (
        <dl className="run-facts" data-advanced="true">
          <dt>{t('desktop.runIdLabel')}</dt>
          <dd>{run.runId}</dd>
          {run.conversationId !== null ? (
            <>
              <dt>{t('desktop.runConversationLabel')}</dt>
              <dd>{run.conversationId}</dd>
            </>
          ) : null}
          {run.workspaceId !== null ? (
            <>
              <dt>{t('desktop.runWorkspaceLabel')}</dt>
              <dd>{run.workspaceId}</dd>
            </>
          ) : null}
          {run.channel ? (
            <>
              <dt>{t('desktop.runChannelLabel')}</dt>
              <dd>{run.channel}</dd>
            </>
          ) : null}
        </dl>
      ) : null}
    </li>
  );
}

/**
 * Advanced-only pairing diagnostics.
 *
 * Easy view renders no version of this panel, so the raw seam text can never
 * leak into the normal-user surface (see #3165).
 */
export function PairingPanel(props: {
  pairing: PairingDeepLinkResponse | null;
  locale: ShellLocale;
  advanced: boolean;
}): ReactElement | null {
  const { pairing, locale, advanced } = props;
  if (!advanced) return null;
  const t = (key: ShellStringKey): string => translate(locale, key);
  return (
    <section className="panel" data-advanced="true">
      <h2>{t('diagnostics.title')}</h2>
      <p className="subtitle">{t('diagnostics.body')}</p>
      <p>{pairing ? pairing.reason : t('diagnostics.seamIdle')}</p>
    </section>
  );
}

/**
 * Advanced-only runner log.
 *
 * #3165 removed the Easy placeholder: Easy view does not mention the log at
 * all, it simply renders no log panel.
 */
export function LogPanel(props: {
  log: BoundedLogResponse | null;
  locale: ShellLocale;
  advanced: boolean;
}): ReactElement | null {
  const { log, locale, advanced } = props;
  if (!advanced) return null;
  const t = (key: ShellStringKey): string => translate(locale, key);
  const lines = log ? log.lines : [];
  return (
    <section className="panel" data-advanced="true">
      <h2>{t('log.title')}</h2>
      <pre className="log">{lines.length === 0 ? t('log.empty') : lines.join('\n')}</pre>
    </section>
  );
}

export function SettingsPanel(props: {
  preferences: ShellUiPreferences;
  onLocale: (locale: ShellLocale) => void;
  onTheme: (theme: ShellThemePreference) => void;
  onView: (view: ShellViewMode) => void;
  onClose: () => void;
}): ReactElement {
  const { preferences, onLocale, onTheme, onView, onClose } = props;
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
        <legend>{t('settings.theme')}</legend>
        {SHELL_THEME_PREFERENCES.map((theme) => (
          <label key={theme}>
            <input
              type="radio"
              name="padiem-theme"
              value={theme}
              checked={preferences.theme === theme}
              onChange={() => onTheme(theme)}
            />
            {theme === 'system'
              ? t('settings.themeSystem')
              : theme === 'light'
                ? t('settings.themeLight')
                : t('settings.themeDark')}
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
  onTheme: (theme: ShellThemePreference) => void;
  onView: (view: ShellViewMode) => void;
  onCloseSettings: () => void;
}): ReactElement {
  const { state, preferences, actions } = props;
  const locale = preferences.locale;
  const t = (key: ShellStringKey): string => translate(locale, key);
  const visibility = visibilityFor(preferences.view);
  return (
    <main
      className="shell"
      data-locale={locale}
      data-view={preferences.view}
      data-theme-preference={preferences.theme}
    >
      <header className="shell-header">
        <div>
          <h1>{t('app.title')}</h1>
          <p className="subtitle">{t('app.tagline')}</p>
        </div>
        <button className="settings-trigger" onClick={props.onToggleSettings}>
          {t('app.settings')}
        </button>
      </header>
      {props.settingsOpen ? (
        <SettingsPanel
          preferences={preferences}
          onLocale={props.onLocale}
          onTheme={props.onTheme}
          onView={props.onView}
          onClose={props.onCloseSettings}
        />
      ) : null}
      <div className="workspace-shell-layout" data-desktop-workspace="stage-b">
        <aside className="workspace-rail workspace-project-rail">
          <WorkspacePanel
            root={state.workspaceRoot}
            listing={state.workspaceListing}
            search={state.workspaceSearch}
            selectedEntry={state.selectedWorkspaceEntry}
            actions={actions}
            locale={locale}
            advanced={visibility.developerFacts}
          />
        </aside>
        <section className="workspace-main">
          <ConversationWorkspacePanel
            locale={locale}
            advanced={visibility.developerFacts}
            conversations={state.conversationList}
            selectedConversation={state.selectedConversation}
            onSelectConversation={(conversationId) => void actions.selectConversation(conversationId)}
          />
          <RunActivityPanel
            locale={locale}
            advanced={visibility.developerFacts}
            runs={state.runList}
          />
        </section>
        <aside className="workspace-rail workspace-local-rail">
          <div className="workspace-rail-title">{t('desktop.localTitle')}</div>
          <ConnectionPanel
            status={state.status}
            busy={state.busy}
            actions={actions}
            locale={locale}
            advanced={visibility.developerFacts}
          />
          <RunnerPanel
            status={state.status}
            health={state.health}
            busy={state.busy}
            actions={actions}
            locale={locale}
            advanced={visibility.developerFacts}
          />
        </aside>
      </div>
      <div className="advanced-diagnostics-grid">
        <PairingPanel
          pairing={state.pairing}
          locale={locale}
          advanced={visibility.rawPairingSeamText}
        />
        <LogPanel log={state.log} locale={locale} advanced={visibility.boundedLogInternals} />
      </div>
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
  const { preferences, setLocale, setTheme, setView } = useUiPreferences();
  const [settingsOpen, setSettingsOpen] = useState(false);

  // #3165 — apply the resolved theme and the language tag to the document.
  // Presentation only: no IPC, no authority, and System mode follows the OS.
  useEffect(() => {
    const media =
      typeof window !== 'undefined' && typeof window.matchMedia === 'function'
        ? window.matchMedia('(prefers-color-scheme: dark)')
        : null;
    const apply = (): void => {
      applyDocumentAppearance(
        document,
        resolveTheme(preferences.theme, media !== null && media.matches),
        preferences.locale,
      );
    };
    apply();
    if (preferences.theme !== 'system' || media === null || typeof media.addEventListener !== 'function') {
      return undefined;
    }
    media.addEventListener('change', apply);
    return () => media.removeEventListener('change', apply);
  }, [preferences.theme, preferences.locale]);

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
      onTheme={setTheme}
      onView={setView}
      onCloseSettings={() => setSettingsOpen(false)}
    />
  );
}
