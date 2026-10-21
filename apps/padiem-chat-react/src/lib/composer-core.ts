/**
 * #5298 — typed access to the canonical shared composer core.
 *
 * `packages/padiem-conversation-ui/composer-core.js` is the single source for
 * the Chat / Claw / B66 composer behaviour (IME composition guard, Enter to
 * send, textarea growth). The clone consumes that source directly instead of
 * re-implementing it, so the clone and the operational product cannot drift
 * apart on input handling.
 *
 * The file is a UMD-style global script: it publishes
 * `globalThis.PadiemConversationComposer` when it is loaded as a script.
 */

import "../../../../packages/padiem-conversation-ui/composer-core.js";

export interface CompositionGuard {
  start(): void;
  update(): void;
  end(): void;
  reset(): void;
  isComposing(): boolean;
}

export interface ComposerCoreApi {
  readonly VERSION: string;
  createCompositionGuard(): CompositionGuard;
  shouldSubmitOnEnter(event: KeyboardEvent, guard?: CompositionGuard): boolean;
  resizeTextarea(
    textarea: HTMLTextAreaElement,
    options?: { minHeight?: number; maxHeight?: number },
  ): number;
}

const runtime = globalThis as typeof globalThis & {
  PadiemConversationComposer?: ComposerCoreApi;
};

const api = runtime.PadiemConversationComposer;

if (!api) {
  throw new Error(
    "packages/padiem-conversation-ui/composer-core.js did not publish PadiemConversationComposer",
  );
}

export const composerCore: ComposerCoreApi = api;
