/**
 * #5298 — typed access to the operational locale and accessibility modules.
 *
 * `apps/padiem-chat/static/locale.js` is the product's own dictionary: the
 * Korean and English copy, the `?lang=` URL contract and the DOM bindings.
 * `apps/padiem-chat/static/a11y.js` owns the confirm dialog and the focus
 * return.
 *
 * The clone reuses both, so a wording change in the product reaches the clone
 * instead of being retyped.
 */

// The locale module reads the attachment capability contract when it loads, so
// that module has to be present first.
import "../../../../apps/padiem-chat/static/attachment-capabilities.js";
import "../../../../apps/padiem-chat/static/locale.js";
import "../../../../apps/padiem-chat/static/a11y.js";

export type LocaleCode = "ko" | "en";

export interface LocaleApi {
  VALID: string[];
  apply(lang: string, persist?: boolean): void;
  getCurrent(): LocaleCode;
  getUrlLocale(): LocaleCode | null;
  text(key: string, variables?: Record<string, unknown> | null): string;
  localizeExisting(): void;
}

export interface ConfirmOptions {
  title?: string;
  message?: string;
  cancelLabel?: string;
  confirmLabel?: string;
}

export interface ConfirmDialogApi {
  confirm(options?: ConfirmOptions): Promise<boolean>;
}

const runtime = globalThis as typeof globalThis & {
  __padiemLocale?: LocaleApi;
  PadiemConfirmDialog?: ConfirmDialogApi;
};

if (!runtime.__padiemLocale) {
  throw new Error("apps/padiem-chat/static/locale.js did not publish __padiemLocale");
}

export const locale: LocaleApi = runtime.__padiemLocale;

/**
 * The operational confirm dialog.
 *
 * It is the product's own destructive-action surface: it traps the focus,
 * answers with a promise and returns the focus to the trigger. The module
 * installs it on load, so the accessor resolves it lazily.
 */
export function confirmDialog(): ConfirmDialogApi | undefined {
  return runtime.PadiemConfirmDialog;
}
