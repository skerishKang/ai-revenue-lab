/**
 * CLAW5 #3157 · CLAW1 #3165 — non-sensitive UI preferences for the desktop renderer.
 *
 * Only three values are ever stored: the display language, the theme and the
 * view mode. All are presentation choices. Nothing here is an authority, and a
 * stored preference can never change the device state, the runner, pairing, the
 * broker or P01. The preference is read through an injected storage port so it
 * is testable and so a hostile or missing storage simply yields the defaults.
 */

import { DEFAULT_LOCALE, isShellLocale, resolveInitialLocale, type ShellLocale } from './i18n.js';

export const SHELL_VIEW_MODES = ['easy', 'advanced'] as const;
export type ShellViewMode = (typeof SHELL_VIEW_MODES)[number];
/** #3157 — Easy is the normal-user default; Advanced is opt-in. */
export const DEFAULT_VIEW_MODE: ShellViewMode = 'easy';

/** #3165 — System follows the OS; Light and Dark are explicit. */
export const SHELL_THEME_PREFERENCES = ['system', 'light', 'dark'] as const;
export type ShellThemePreference = (typeof SHELL_THEME_PREFERENCES)[number];
export const DEFAULT_THEME_PREFERENCE: ShellThemePreference = 'system';

export const UI_PREFERENCE_STORAGE_KEY = 'padiem.desktop.ui.v1';

export interface UiPreferenceStorage {
  read(key: string): string | null;
  write(key: string, value: string): void;
}

export interface ShellUiPreferences {
  readonly locale: ShellLocale;
  readonly theme: ShellThemePreference;
  readonly view: ShellViewMode;
}

export function isShellViewMode(value: unknown): value is ShellViewMode {
  return typeof value === 'string' && (SHELL_VIEW_MODES as readonly string[]).includes(value);
}

export function isShellThemePreference(value: unknown): value is ShellThemePreference {
  return (
    typeof value === 'string' && (SHELL_THEME_PREFERENCES as readonly string[]).includes(value)
  );
}

/**
 * Resolve a theme preference to the theme actually rendered.
 *
 * `system` follows the OS; an explicit choice always wins over the OS. The
 * result is a presentation value only — it is never device or runner state.
 */
export function resolveTheme(
  preference: ShellThemePreference,
  systemPrefersDark: boolean,
): 'light' | 'dark' {
  if (preference === 'light') return 'light';
  if (preference === 'dark') return 'dark';
  return systemPrefersDark ? 'dark' : 'light';
}

/** The renderer-local store, isolated so tests never touch a real window. */
export function createLocalPreferenceStorage(backing?: {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}): UiPreferenceStorage {
  return {
    read(key) {
      try {
        return backing ? backing.getItem(key) : null;
      } catch {
        return null;
      }
    },
    write(key, value) {
      try {
        backing?.setItem(key, value);
      } catch {
        // A read-only or full storage must never break the app.
      }
    },
  };
}

const EMPTY_STORAGE: UiPreferenceStorage = Object.freeze({
  read: () => null,
  write: () => undefined,
});

function parse(raw: string | null): Record<string, unknown> | null {
  if (typeof raw !== 'string' || raw.trim() === '') return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return null;
    return parsed as Record<string, unknown>;
  } catch {
    return null;
  }
}

/**
 * Load the stored preferences, falling back to the host locale, the system
 * theme and Easy mode.
 *
 * A stored value that is not exactly one of the known choices is discarded
 * rather than guessed at, and any extra key in storage is dropped on write so
 * a preference record can never become a place to stash something else.
 */
export function loadUiPreferences(
  storage: UiPreferenceStorage = EMPTY_STORAGE,
  hostLocale?: unknown,
): ShellUiPreferences {
  let raw: string | null = null;
  try {
    raw = storage.read(UI_PREFERENCE_STORAGE_KEY);
  } catch {
    // A storage that refuses to answer is a missing preference, never a crash.
    raw = null;
  }
  const stored = parse(raw);
  return {
    locale: isShellLocale(stored?.['locale'])
      ? stored['locale']
      : resolveInitialLocale(hostLocale ?? DEFAULT_LOCALE),
    theme: isShellThemePreference(stored?.['theme'])
      ? stored['theme']
      : DEFAULT_THEME_PREFERENCE,
    view: isShellViewMode(stored?.['view']) ? stored['view'] : DEFAULT_VIEW_MODE,
  };
}

export function saveUiPreferences(
  storage: UiPreferenceStorage,
  preferences: ShellUiPreferences,
): ShellUiPreferences {
  const next: ShellUiPreferences = {
    locale: isShellLocale(preferences.locale) ? preferences.locale : DEFAULT_LOCALE,
    theme: isShellThemePreference(preferences.theme)
      ? preferences.theme
      : DEFAULT_THEME_PREFERENCE,
    view: isShellViewMode(preferences.view) ? preferences.view : DEFAULT_VIEW_MODE,
  };
  try {
    storage.write(UI_PREFERENCE_STORAGE_KEY, JSON.stringify(next));
  } catch {
    // An unwritable store means the choice is simply not remembered; the value
    // the user just picked still applies for the rest of this session.
  }
  return next;
}

export const UI_PREFERENCES_ARE_NON_SENSITIVE = true;
export const STORED_PREFERENCE_KEYS = Object.freeze(['locale', 'theme', 'view']);
export const THEME_PREFERENCE_IS_NON_SENSITIVE = true;
export const PREFERENCE_CAN_CHANGE_DEVICE_STATE = false;
export const PREFERENCE_CAN_CHANGE_RUNNER_STATE = false;
export const PREFERENCE_CAN_CHANGE_PAIRING_OR_P01 = false;
export const PRODUCTION_MUTATION = false;
