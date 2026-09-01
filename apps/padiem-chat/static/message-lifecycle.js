(() => {
  "use strict";

  const states = Object.freeze({
    STREAMING: "streaming",
    COMPLETED: "completed",
    FAILED: "failed",
    CANCELLED: "cancelled",
    TIMED_OUT: "timed_out",
  });

  window.PadiemChatLifecycle = Object.freeze({
    states,
    isCompleted(article) {
      return Boolean(article && article.dataset.lifecycle === states.COMPLETED);
    },
    set(article, state) {
      if (!article || !Object.values(states).includes(state)) return;
      article.dataset.lifecycle = state;
      article.dispatchEvent(new CustomEvent("padiem:message-lifecycle", {
        bubbles: true,
        detail: { state },
      }));
    },
  });
})();
