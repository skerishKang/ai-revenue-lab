/* The install file's 10-minute clock, shared by the Connectors PC card and the
 * 내 컴퓨터 guide (#7962). The server owns the deadline: it stamps the same
 * expiry into the download response that it enforces, and its polling answer
 * reports each code's state. This module only reads those two things - it never
 * holds or prints a code or a token value.
 */
(() => {
  "use strict";
  // list_codes reports the install state. `expired` is what it answers for a
  // pending code whose clock ran out, `cancelled` is the owner's cancel or a
  // revoked token, and the token states say the file itself no longer works.
  // `claimed` is a success, so it is deliberately absent.
  const DEAD_CODE_STATES = new Set(["expired", "cancelled"]);
  const DEAD_TOKEN_STATES = new Set(["expired", "revoked"]);

  function isDead(code) {
    if (!code) return false;
    return DEAD_CODE_STATES.has(code.state)
      || DEAD_TOKEN_STATES.has(code.install_token_state);
  }

  function findCode(codes, codeId) {
    if (!codeId || !Array.isArray(codes)) return null;
    return codes.find((code) => code && code.code_id === codeId) || null;
  }

  // Seconds left on the server's deadline, or null when the answer carries
  // none. A missing expiry keeps the one static sentence and no timer.
  function secondsLeft(expiresAt, now) {
    const stamp = Date.parse(expiresAt || "");
    if (!Number.isFinite(stamp)) return null;
    return Math.ceil((stamp - (now === undefined ? Date.now() : now)) / 1000);
  }

  function isStamped(expiresAt) {
    return secondsLeft(expiresAt) !== null;
  }

  // #8915: the browser clock and the server's can disagree, and a clock that
  // runs ahead makes every fresh file look already expired. The download
  // response carries the server's own Date header, so the offset between the
  // two clocks turns the deadline judgment into server time. A response
  // without the header keeps the browser clock (null).
  function skew(dateHeader) {
    const stamp = Date.parse(dateHeader || "");
    return Number.isFinite(stamp) ? stamp - Date.now() : null;
  }

  function formatRemaining(totalSeconds) {
    const minutes = Math.floor(totalSeconds / 60);
    const clock = String(totalSeconds % 60).padStart(2, "0");
    const english = (document.documentElement.lang || "ko").toLowerCase()
      .startsWith("en");
    return english ? `${minutes}m ${clock}s` : `${minutes}분 ${clock}초`;
  }

  window.PadiemPcInstallDeadline = {
    isDead,
    findCode,
    secondsLeft,
    isStamped,
    skew,
    formatRemaining,
  };
})();