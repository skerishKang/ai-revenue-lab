(() => {
  "use strict";
  function bind({ clearHistoryUI, clearProjectsUI, resetConversationView,
    hasAndroidHandoff, clearAndroidHandoff, clearHandoffStorage }) {
    let hadSignedInSession = false;
    window.addEventListener("padiem:auth-state", (event) => {
      const session = window.PadiemAuthSession.get();
      const authenticated = session ? session.authenticated : event.detail.authenticated === true;
      const signedInLost = hadSignedInSession && !authenticated;
      hadSignedInSession = authenticated;
      if (authenticated && hasAndroidHandoff()) clearAndroidHandoff();
      // Initial/repeated guest projections must not clear drafts or steal focus.
      if (signedInLost) {
        resetConversationView(false);
        clearHandoffStorage();
      }
      if (!authenticated) {
        clearHistoryUI();
        clearProjectsUI();
      }
    });
    // Guest badge copy still follows locale changes even when auth is unchanged.
    window.addEventListener("padiem:localechange", () => {
      const session = window.PadiemAuthSession.get();
      if (session && !session.authenticated) clearProjectsUI();
    });
  }
  window.PadiemChatSession = Object.freeze({ bind });
})();
