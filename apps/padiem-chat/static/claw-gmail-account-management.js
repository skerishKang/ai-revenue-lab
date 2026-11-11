/* Gmail account removal lives in Connectors, never the ON/OFF switch (#7088 4/4).
 * Same flow as the Drive card: a two-click confirm, one empty-body POST to the
 * reviewed disconnect route, a verified {ok,state:"off"} answer, then one
 * status refresh so the card flips to "not connected". Copy comes from
 * locale.js (ko+en) through window.__padiemLocale.text — this module never
 * inlines owner-facing wording.
 */
(() => {
  "use strict";
  const dialog = document.getElementById("connectorsDialog");
  const card = document.querySelector('[data-connector-id="connector:google:gmail@1"]');
  const remove = document.getElementById("connectorGmailRemove");
  const feedback = document.getElementById("connectorGmailFeedback");
  if (!dialog || !card || !remove || !feedback) return;
  const localeText = (key) => {
    const locale = window.__padiemLocale;
    return locale && typeof locale.text === "function" ? locale.text(key) : key;
  };
  let pending = false;
  let confirmed = false;
  const show = (element, visible) => { element.hidden = !visible; };
  const write = (element, value) => { element.textContent = value; };
  const connected = () => card.dataset.connectorStatus === "connected";
  const render = () => {
    show(remove, connected());
    remove.disabled = pending;
    if (!connected()) confirmed = false;
    write(remove, confirmed ? localeText("connectors-gmail-remove-confirm-button")
                            : localeText("connectors-gmail-remove"));
  };
  async function disconnect() {
    const response = await fetch("/api/connectors/google/gmail/disconnect", {
      method: "POST", credentials: "same-origin", cache: "no-store",
      headers: { "Accept": "application/json" }
    });
    const body = await response.json().catch(() => null);
    if (!response.ok || body?.ok !== true || body.state !== "off") {
      throw Error("disconnect not verified");
    }
  }
  remove.addEventListener("click", async () => {
    if (pending || !connected()) return;
    if (!confirmed) {
      confirmed = true;
      write(feedback, localeText("connectors-gmail-remove-confirm"));
      show(feedback, true);
      render();
      return;
    }
    pending = true; render();
    try {
      await disconnect();
      confirmed = false;
      // One status refresh re-renders the card as "not connected" from the
      // server's own answer; this module never writes the status itself.
      document.dispatchEvent(new Event("padiem:refresh-connector-status"));
      window.dispatchEvent(new Event("focus"));
      write(feedback, localeText("connectors-gmail-removed"));
      show(feedback, true);
    } catch (_) {
      write(feedback, localeText("connectors-gmail-remove-failed"));
      show(feedback, true);
    } finally { pending = false; confirmed = false; render(); }
  });
  new MutationObserver(render).observe(card, { attributes: true, attributeFilter: ["data-connector-status"] });
  dialog.addEventListener("close", () => { confirmed = false; show(feedback, false); render(); });
  render();
})();
