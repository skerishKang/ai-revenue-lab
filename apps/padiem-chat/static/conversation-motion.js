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
  var messageObserver = null;
  var composerObserver = null;

  function prefersReducedMotion(){
    try {
      return Boolean(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
    } catch (_) {
      return false;
    }
  }

  function inChat(){
    return Boolean(
      shell
      && shell.dataset.state === "chat"
      && document.documentElement.getAttribute("data-theme") === "padiem-glass"
    );
  }

  function documentHeight(){
    var root = document.documentElement;
    var body = document.body;
    return Math.max(
      root ? root.scrollHeight : 0,
      body ? body.scrollHeight : 0
    );
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

  function nearConversationEnd(){
    var clearance = syncComposerClearance();
    var remaining = documentHeight() - ((window.scrollY || 0) + window.innerHeight);
    return remaining <= Math.max(FOLLOW_THRESHOLD, Math.round(clearance * 0.72));
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
    if (!inChat()) return;
    syncComposerClearance();
    markProgrammaticScroll();
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
    if (!inChat()) return;
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
    if (!inChat()) return;
    if (!force && !followLatest) return;
    if (followFrame) cancelAnimationFrame(followFrame);
    followFrame = requestAnimationFrame(function(){
      followFrame = 0;
      if (!inChat()) return;
      if (anchorTurn) anchorNewestTurn();
      else if (force || followLatest) scrollPageToEnd("auto");
    });
  }

  function addedNodeContainsUser(node){
    if (!node || node.nodeType !== Node.ELEMENT_NODE) return false;
    if (node.matches && node.matches(".user-message")) return true;
    return Boolean(node.querySelector && node.querySelector(".user-message"));
  }

  function observeMessages(){
    if (!messageList || !window.MutationObserver || messageObserver) return;
    messageObserver = new MutationObserver(function(mutations){
      if (!inChat()) return;
      var sawUser = false;
      var changed = false;
      mutations.forEach(function(mutation){
        if (mutation.type === "characterData") changed = true;
        if (mutation.type === "childList") {
          if (mutation.addedNodes.length || mutation.removedNodes.length) changed = true;
          mutation.addedNodes.forEach(function(node){
            if (addedNodeContainsUser(node)) sawUser = true;
          });
        }
      });
      if (sawUser) queueFollow(true, true);
      else if (changed) queueFollow(false, false);
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
      if (followLatest && inChat()) queueFollow(false, false);
    });
    composerObserver.observe(composerWrap);
  }

  function handleScroll(){
    var currentY = window.scrollY || document.documentElement.scrollTop || 0;
    if (performance.now() > suppressDirectionUntil && currentY < lastScrollY - 6) {
      followLatest = false;
    } else if (nearConversationEnd()) {
      followLatest = true;
    }
    lastScrollY = currentY;
    syncFollowState();
  }

  function handlePointerWheel(event){
    if (event.deltaY < 0 && inChat()) {
      followLatest = false;
      syncFollowState();
    }
  }

  function init(){
    shell = document.querySelector(".app-shell");
    messageList = document.getElementById("messageList");
    composerWrap = document.querySelector(".composer-wrap");
    if (!shell || !messageList || !composerWrap) return;

    lastScrollY = window.scrollY || document.documentElement.scrollTop || 0;
    syncFollowState();
    observeMessages();
    observeComposer();

    window.addEventListener("scroll", handleScroll, { passive: true });
    window.addEventListener("wheel", handlePointerWheel, { passive: true });
    window.addEventListener("resize", function(){
      syncComposerClearance();
      if (followLatest && inChat()) queueFollow(false, false);
    });

    window.__padiemConversationMotion = {
      isFollowingLatest: function(){ return followLatest; },
      resume: function(){
        followLatest = true;
        syncFollowState();
        queueFollow(true, false);
      },
      syncComposerClearance: syncComposerClearance
    };
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();
