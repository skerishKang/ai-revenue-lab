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
  // #5014: the Chat first screen ("home") is the same conversation panel with
  // the starter cards instead of turns, and it shares the same fixed
  // composer, so it follows the same reservation.
  function inConversation(){
    if (!shell || document.documentElement.getAttribute("data-theme") !== "padiem-glass") {
      return false;
    }
    var state = shell.dataset.state;
    if (state === "home" || state === "chat") return true;
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

  /* #5014: the composer lane measures the fixed input and publishes the
   * reserved clearance. The conversation lane only READS that value: two
   * writers with different floors used to race for the same custom property,
   * so the reserved space could differ from the band the input actually
   * occupies. Until the composer lane publishes, the stylesheet default
   * applies and the follow threshold falls back to its own minimum. */
  function publishedClearance(){
    var raw = window.getComputedStyle(document.documentElement)
      .getPropertyValue("--padiem-composer-clearance");
    var value = parseFloat(raw);
    return isFinite(value) && value > 0 ? value : 0;
  }

  function syncComposerClearance(){
    return publishedClearance();
  }

  function remainingToEnd(){
    var conv = scrollableConversation();
    if (conv) {
      /* #4488: one shared container-gap calculation with B66. The jump limit
       * (FOLLOW_THRESHOLD + composer clearance) and the window/document scroll
       * fallback below stay owned by this product surface. */
      var shared = window.PadiemConversationScroll || window.SharedConversationScroll;
      if (shared && typeof shared.remainingToEnd === "function") {
        return shared.remainingToEnd(conv);
      }
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

  /* #5014: the fixed composer overlays the bottom of the conversation surface.
   * The reserved clearance lets the newest content scroll ABOVE the input, but
   * the surface also has to OPEN there: a first screen whose last card row or
   * last turn already starts under the glass input reads as a broken layout.
   * The landing moves by the SMALLEST scroll that clears the composer, so the
   * greeting stays visible whenever the content still fits above the input.
   * A reader who scrolled back is never moved, because this only runs while
   * following. */
  function landingBreathingRoom(){
    /* The breathing room is the one the surface already declares for itself:
     * the scroll padding sits the reserved clearance plus a small gap above
     * the input, so the landing reuses that gap instead of a second
     * hard-coded number. */
    if (!conversation) return 0;
    var style = window.getComputedStyle(conversation);
    var padding = parseFloat(style.paddingBottom);
    var scrollPadding = parseFloat(style.scrollPaddingBottom);
    if (!isFinite(padding) || !isFinite(scrollPadding)) return 0;
    return Math.max(0, Math.round(scrollPadding - padding));
  }

  function lowestContentBottom(root){
    /* The lowest painted edge of the conversation content. Hidden subtrees are
     * skipped as a whole, so a hidden section costs one measurement. */
    var best = null;
    var stack = [];
    for (var i = 0; i < root.children.length; i += 1) stack.push(root.children[i]);
    while (stack.length) {
      var el = stack.pop();
      var rect = el.getBoundingClientRect();
      if (!rect || (rect.width < 1 && rect.height < 1)) continue;
      var style = window.getComputedStyle(el);
      if (!style || style.display === "none" || style.visibility === "hidden") continue;
      if (style.position === "fixed") continue;
      if (best === null || rect.bottom > best) best = rect.bottom;
      for (var j = 0; j < el.children.length; j += 1) stack.push(el.children[j]);
    }
    return best;
  }

  function landingScrollSurface(){
    /* The panel is its own scrollport on a desktop frame. A phone surface
     * scrolls the document instead, so the landing has to move whichever
     * surface actually scrolls. */
    var conv = scrollableConversation();
    if (conv) {
      return {
        current: conv.scrollTop,
        limit: Math.max(0, conv.scrollHeight - conv.clientHeight),
        apply: function(value){
          conv.scrollTo({ top: value, behavior: "auto" });
        }
      };
    }
    return {
      current: window.scrollY || document.documentElement.scrollTop || 0,
      limit: Math.max(0, documentHeight() - window.innerHeight),
      apply: function(value){
        window.scrollTo({ top: Math.max(0, value), behavior: "auto" });
      }
    };
  }

  function landLatestContent(){
    if (!inConversation()) return;
    if (!followLatest) return;
    if (!conversation || !composerWrap) return;
    var composerRect = composerWrap.getBoundingClientRect();
    var limit = composerRect.top - landingBreathingRoom();
    var bottom = lowestContentBottom(conversation);
    if (bottom === null) return;
    var needed = bottom - limit;
    if (needed <= 1) return;
    var surface = landingScrollSurface();
    var target = Math.min(surface.current + needed, surface.limit);
    if (target <= surface.current + 1) return;
    markProgrammaticScroll();
    surface.apply(target);
  }

  /* #5014: "follow the latest content" means two different things. A live
   * thread follows its newest turn to the end. A first screen has no turn, so
   * it follows its last card to the first position that clears the input. */
  function isLandingSurface(){
    if (!messageList || messageList.children.length > 0) return false;
    var empty = document.getElementById("emptyState");
    return Boolean(empty && !empty.hasAttribute("hidden"));
  }

  function followLatestContent(){
    if (isLandingSurface()) {
      landLatestContent();
      return;
    }
    scrollPageToEnd("auto");
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
      else if (force || followLatest) followLatestContent();
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
    landLatestContent();
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
    if (!window.ResizeObserver || composerObserver) return;
    composerObserver = new ResizeObserver(function(){
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
      syncJumpButton();
      if (followLatest && inConversation()) queueFollow(false, false);
    });
    /* #5014: the first screen has to open with the newest content already
     * clear of the fixed composer. The web fonts and the device directory
     * change the measured composer height after the first paint, so the
     * landing runs again once the document is complete. */
    window.addEventListener("load", function(){
      landLatestContent();
    });
    if (document.fonts && typeof document.fonts.ready === "object") {
      document.fonts.ready.then(function(){
        landLatestContent();
      });
    }

    landLatestContent();

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
