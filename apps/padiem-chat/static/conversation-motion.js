(function(){
  "use strict";

  var FOLLOW_THRESHOLD = 180;
  var followLatest = true;
  var lastScrollY = 0;
  var suppressDirectionUntil = 0;
  var followFrame = 0;
  var messageList = null;
  var composerWrap = null;
  var shell = null;
  var conversation = null;
  var messageObserver = null;
  var composerObserver = null;
  var shellObserver = null;
  var jumpButton = null;

  function prefersReducedMotion(){
    try {
      return Boolean(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
    } catch (_) {
      return false;
    }
  }

  // One shared Chat/Claw conversation lane. Claw runs the same message list on
  // the general/manual workbench, so it must follow and offer the jump control
  // exactly like Chat. The Claw workbench (inbox = tasks/alerts) is not a
  // conversation surface and is excluded here.
  function inConversation(){
    if (!shell || document.documentElement.getAttribute("data-theme") !== "padiem-glass") {
      return false;
    }
    var state = shell.dataset.state;
    if (state === "chat") return true;
    if (state === "claw") {
      var workspace = document.getElementById("clawWorkspace");
      return !workspace || workspace.dataset.view !== "inbox";
    }
    return false;
  }

  function documentHeight(){
    var root = document.documentElement;
    var body = document.body;
    return Math.max(
      root ? root.scrollHeight : 0,
      body ? body.scrollHeight : 0
    );
  }

  // At >=921px shared-six-panel-frame.css turns `.conversation` into a
  // self-contained scroll panel (overflow-y:auto + fixed height), so the
  // document has nothing left to scroll and `window.scrollY` stays constant.
  // Follow must drive whichever surface actually scrolls, otherwise it silently
  // measures a no-op and the appended tail hides behind the fixed composer.
  function scrollableConversation(){
    if (conversation && conversation.scrollHeight > conversation.clientHeight + 1) {
      return conversation;
    }
    return null;
  }

  function currentScrollTop(){
    var conv = scrollableConversation();
    if (conv) return conv.scrollTop;
    return window.scrollY || document.documentElement.scrollTop || 0;
  }

  function composerHeight(){
    if (!composerWrap) return 0;
    return Math.ceil(composerWrap.getBoundingClientRect().height || 0);
  }

  function syncComposerClearance(){
    var root = document.documentElement;
    var clearance = Math.max(220, composerHeight() + 64);
    root.style.setProperty("--padiem-composer-clearance", clearance + "px");
    return clearance;
  }

  function remainingToEnd(){
    var conv = scrollableConversation();
    if (conv) {
      return conv.scrollHeight - conv.scrollTop - conv.clientHeight;
    }
    return documentHeight() - ((window.scrollY || 0) + window.innerHeight);
  }

  function nearConversationEnd(){
    var clearance = syncComposerClearance();
    var limit = Math.max(FOLLOW_THRESHOLD, Math.round(clearance * 0.72));
    return remainingToEnd() <= limit;
  }

  // One shared Chat/Claw jump control. This module owns it, so no product
  // surface duplicates follow state; it exists only on the conversation lane
  // and never on the Claw workbench.
  function ensureJumpButton(){
    if (jumpButton || !composerWrap) return jumpButton;
    jumpButton = document.createElement("button");
    jumpButton.type = "button";
    jumpButton.id = "conversationJumpButton";
    jumpButton.className = "conversation-jump";
    jumpButton.textContent = "↓";
    jumpButton.hidden = true;
    jumpButton.setAttribute("aria-label", "최신 메시지로 이동");
    jumpButton.setAttribute("data-locale-aria-label", "conversation-jump");
    jumpButton.setAttribute("data-locale-title", "conversation-jump");
    jumpButton.addEventListener("click", function(){
      resumeFollow();
    });
    composerWrap.appendChild(jumpButton);
    return jumpButton;
  }

  function syncJumpButton(){
    var button = ensureJumpButton();
    if (!button) return;
    var show = inConversation() && !nearConversationEnd();
    button.hidden = !show;
  }

  function syncFollowState(){
    document.documentElement.setAttribute(
      "data-conversation-follow",
      followLatest ? "latest" : "paused"
    );
  }

  function markProgrammaticScroll(){
    suppressDirectionUntil = performance.now() + 500;
  }

  function scrollPageToEnd(behavior){
    if (!inConversation()) return;
    syncComposerClearance();
    markProgrammaticScroll();
    var conv = scrollableConversation();
    if (conv) {
      conv.scrollTo({ top: conv.scrollHeight, behavior: behavior || "auto" });
      return;
    }
    window.scrollTo({
      top: Math.max(0, documentHeight() - window.innerHeight),
      behavior: behavior || "auto"
    });
  }

  function latestUserMessage(){
    if (!messageList) return null;
    var users = messageList.querySelectorAll(".user-message");
    return users.length ? users[users.length - 1] : null;
  }

  function anchorNewestTurn(){
    if (!inConversation()) return;
    var user = latestUserMessage();
    if (!user) {
      scrollPageToEnd("auto");
      return;
    }
    followLatest = true;
    syncFollowState();
    syncComposerClearance();
    markProgrammaticScroll();
    user.scrollIntoView({
      block: "start",
      behavior: prefersReducedMotion() ? "auto" : "smooth"
    });
  }

  function queueFollow(force, anchorTurn){
    if (!inConversation()) {
      syncJumpButton();
      return;
    }
    if (!force && !followLatest) return;
    if (followFrame) cancelAnimationFrame(followFrame);
    followFrame = requestAnimationFrame(function(){
      followFrame = 0;
      if (!inConversation()) {
        syncJumpButton();
        return;
      }
      if (anchorTurn) anchorNewestTurn();
      else if (force || followLatest) scrollPageToEnd("auto");
      syncJumpButton();
    });
  }

  function resumeFollow(){
    followLatest = true;
    syncFollowState();
    queueFollow(true, false);
    syncJumpButton();
  }

  // New chat, saved-conversation open and Chat<->Claw switches must start from
  // "following the latest turn" instead of inheriting a paused state.
  function reset(){
    followLatest = true;
    lastScrollY = currentScrollTop();
    syncFollowState();
    syncJumpButton();
  }

  function addedNodeContainsUser(node){
    if (!node || node.nodeType !== Node.ELEMENT_NODE) return false;
    if (node.matches && node.matches(".user-message")) return true;
    return Boolean(node.querySelector && node.querySelector(".user-message"));
  }

  function observeMessages(){
    if (!messageList || !window.MutationObserver || messageObserver) return;
    messageObserver = new MutationObserver(function(mutations){
      if (!inConversation()) {
        syncJumpButton();
        return;
      }
      var addedUsers = 0;
      var changed = false;
      mutations.forEach(function(mutation){
        if (mutation.type === "characterData") changed = true;
        if (mutation.type === "childList") {
          if (mutation.addedNodes.length || mutation.removedNodes.length) changed = true;
          mutation.addedNodes.forEach(function(node){
            if (addedNodeContainsUser(node)) addedUsers += 1;
          });
        }
      });
      if (addedUsers > 1) {
        // A saved conversation restores as one bulk batch: follow the newest
        // turn to the bottom instead of anchoring the last user turn to top.
        resumeFollow();
      } else if (addedUsers === 1) {
        queueFollow(true, true);
      } else if (changed) {
        queueFollow(false, false);
      }
      syncJumpButton();
    });
    messageObserver.observe(messageList, {
      childList: true,
      subtree: true,
      characterData: true
    });
  }

  function observeComposer(){
    if (!composerWrap) return;
    syncComposerClearance();
    if (!window.ResizeObserver || composerObserver) return;
    composerObserver = new ResizeObserver(function(){
      syncComposerClearance();
      syncJumpButton();
      if (followLatest && inConversation()) queueFollow(false, false);
    });
    composerObserver.observe(composerWrap);
  }

  function handleScroll(){
    var currentY = currentScrollTop();
    if (performance.now() > suppressDirectionUntil && currentY < lastScrollY - 6) {
      followLatest = false;
    } else if (nearConversationEnd()) {
      followLatest = true;
    }
    lastScrollY = currentY;
    syncFollowState();
    syncJumpButton();
  }

  function handlePointerWheel(event){
    if (event.deltaY < 0 && inConversation()) {
      followLatest = false;
      syncFollowState();
      syncJumpButton();
    }
  }

  function observeShellState(){
    if (!shell || !window.MutationObserver || shellObserver) return;
    shellObserver = new MutationObserver(function(){
      reset();
    });
    shellObserver.observe(shell, { attributes: true, attributeFilter: ["data-state"] });
  }

  function init(){
    shell = document.querySelector(".app-shell");
    messageList = document.getElementById("messageList");
    composerWrap = document.querySelector(".composer-wrap");
    conversation = document.querySelector(".conversation");
    if (!shell || !messageList || !composerWrap) return;

    lastScrollY = currentScrollTop();
    syncFollowState();
    observeMessages();
    observeComposer();
    observeShellState();
    syncJumpButton();

    window.addEventListener("scroll", handleScroll, { passive: true });
    if (conversation) {
      conversation.addEventListener("scroll", handleScroll, { passive: true });
    }
    window.addEventListener("wheel", handlePointerWheel, { passive: true });
    window.addEventListener("resize", function(){
      syncComposerClearance();
      syncJumpButton();
      if (followLatest && inConversation()) queueFollow(false, false);
    });

    window.__padiemConversationMotion = {
      isFollowingLatest: function(){ return followLatest; },
      resume: resumeFollow,
      reset: reset,
      syncComposerClearance: syncComposerClearance
    };
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();
