// Wait for the existing authoritative auth-state event before private reads.
(() => {
  "use strict";
  let authenticated = false;
  window.addEventListener("padiem:auth-state", event => {
    authenticated = event.detail?.authenticated === true;
  });
  window.PadiemAuthGate = Object.freeze({ authenticated: () => authenticated });
})();
