/**
 * #5298 — the operational glass shell layer.
 *
 * `apps/padiem-chat/static/padiem-glass-shell.js` builds the portrait and the
 * 20 registered shell ribbons that the glass theme paints over the clean
 * portrait. The clone reuses that module instead of drawing its own, so the
 * default theme looks the same in both builds.
 *
 * The module is a classic script that reads `.main-panel` when it installs, so
 * it is imported after React mounted the shell instead of at module load.
 */
export async function mountOperationalGlassShell(): Promise<void> {
  await import("../../../../apps/padiem-chat/static/padiem-glass-shell.js");
}
