(() => {
  "use strict";
  // R5 B1: the shared app context — the module registry (rule (d)) and the
  // namespace the pilot zones read shared state through (rule (c)). app.js
  // Remaining closure-owned refs are mounted here as live accessors.
  const app = window.PadiemChatAppContext.create({
    get clawConversationIds() { return clawConversationIds; },
    get clawConversationLabelsRead() { return clawConversationLabelsRead; },
    get selectedAttachments() { return selectedAttachments; },
    set clawConversationLabelsRead(value) { clawConversationLabelsRead = value; },
    set selectedAttachments(value) { selectedAttachments = value; },
    get shell() { return shell; },
    get clawWorkspace() { return clawWorkspace; },
    get emptyState() { return emptyState; },
    get clawRunHistoryPdfControllers() { return clawRunHistoryPdfControllers; },
    get clawRunHistoryInFlight() { return clawRunHistoryInFlight; },
    set clawRunHistoryInFlight(value) { clawRunHistoryInFlight = value; },
    get clawRunHistoryLimit() { return clawRunHistoryLimit; },
    set clawRunHistoryLimit(value) { clawRunHistoryLimit = value; },
    get pendingClawRunFocusId() { return pendingClawRunFocusId; },
    set pendingClawRunFocusId(value) { pendingClawRunFocusId = value; },
      get ALLOWED_IMAGE_TYPES() { return ALLOWED_IMAGE_TYPES; },
    get MESSAGE_LIFECYCLE() { return MESSAGE_LIFECYCLE; },
    get PRODUCT_CHAT() { return PRODUCT_CHAT; },
    get PRODUCT_CLAW() { return PRODUCT_CLAW; },
    get accountContainer() { return accountContainer; },
    get accountDeleteConfirm() { return accountDeleteConfirm; },
    get accountName() { return accountName; },
    get activeClawRunId() { return activeClawRunId; },
    set activeClawRunId(value) { activeClawRunId = value; },

    get activeRequestArticle() { return activeRequestArticle; },
    set activeRequestArticle(value) { activeRequestArticle = value; },
    get activeRequestCancelReason() { return activeRequestCancelReason; },
    set activeRequestCancelReason(value) { activeRequestCancelReason = value; },
    get activeRequestController() { return activeRequestController; },
    set activeRequestController(value) { activeRequestController = value; },
    get advancedSettingsView() { return settings.dom.advancedSettingsView; },
    get authDialog() { return authDialog; },
    get chatTransport() { return chatTransport; },
    get clawAction() { return clawAction; },
    get clawApprovalEpoch() { return clawApprovalEpoch; },
    set clawApprovalEpoch(value) { clawApprovalEpoch = value; },
    get clawApprovalInFlight() { return clawApprovalInFlight; },
    set clawApprovalInFlight(value) { clawApprovalInFlight = value; },
    get clawArtifactShownFor() { return clawArtifactShownFor; },
    set clawArtifactShownFor(value) { clawArtifactShownFor = value; },
    get clawChannel() { return clawChannel; },
    get clawExecuteButton() { return clawExecuteButton; },
    get clawInFlight() { return clawInFlight; },
    set clawInFlight(value) { clawInFlight = value; },
    get clawLastDispatchKey() { return clawLastDispatchKey; },
    set clawLastDispatchKey(value) { clawLastDispatchKey = value; },
    get clawManualForm() { return clawManualForm; },
    get clawResultArea() { return clawResultArea; },
    get clawResultCard() { return clawResultCard; },
    get clawResultDocx() { return clawResultDocx; },
    get clawResultEmpty() { return clawResultEmpty; },
    get clawResultHint() { return clawResultHint; },
    get clawResultPreview() { return clawResultPreview; },
    get clawRetryButton() { return clawRetryButton; },
    get clawSender() { return clawSender; },
    get connectorsError() { return connectorsError; },
    get conversationArtifactContext() { return conversationArtifactContext; },
    get conversationEpoch() { return conversationEpoch; },
    set conversationEpoch(value) { conversationEpoch = value; },
    get conversationProduct() { return conversationProduct; },
    set conversationProduct(value) { conversationProduct = value; },
    get conversationState() { return conversationState; },
    get googleConnectorConnectInFlight() { return googleConnectorConnectInFlight; },
    set googleConnectorConnectInFlight(value) { googleConnectorConnectInFlight = value; },
    get historyActionStatus() { return historyActionStatus; },
    get historyEmpty() { return historyEmpty; },
    get historyList() { return historyList; },
    get historySection() { return historySection; },
    get inFlight() { return inFlight; },
    set inFlight(value) { inFlight = value; },
    get input() { return input; },
    get lastCompletedAnswerRequest() { return lastCompletedAnswerRequest; },
    set lastCompletedAnswerRequest(value) { lastCompletedAnswerRequest = value; },
    get messageList() { return messageList; },
    get passwordLoginError() { return passwordLoginError; },
    get passwordResetConfirmError() { return passwordResetConfirmError; },
    get passwordResetConfirmStatus() { return passwordResetConfirmStatus; },
    get passwordResetConfirmView() { return passwordResetConfirmView; },
    get passwordResetEmail() { return passwordResetEmail; },
    get passwordResetNew() { return passwordResetNew; },
    get passwordResetOpen() { return passwordResetOpen; },
    get passwordResetPanel() { return passwordResetPanel; },
    get passwordResetRequestError() { return passwordResetRequestError; },
    get passwordResetRequestStatus() { return passwordResetRequestStatus; },
    get passwordResetRequestView() { return passwordResetRequestView; },
    get profileToggle() { return profileToggle; },
    get settingsButton() { return settings.dom.settingsButton; },
}, {
    core: () => coreModule(),
    nav: () => navModuleInstance,
    sidebar: () => sidebar,
    clawStatus: () => clawStatusModule(),
    conversation: () => conversationModule(),
    clawRun: () => clawRun,
    auth: () => authModule(),
    loginDialog: () => loginDialogModule(),
    settings: () => settings,
    project: () => projectModule,
    history: () => historyModule(),
    runHistory: () => runHistory,
  });
  // #7216 R5 A7 (core): text lookup, note, error mapping, document readers,
  // formatters live in chat-core-module.js. app.js keeps one-line forwarders
  // and passes dependencies via getters.
  let coreModuleInstance = null;
  function coreModule() {
    if (!coreModuleInstance) {
      coreModuleInstance = app.provide("core", window.PadiemChatCoreModule.create(Object.setPrototypeOf({

        get runtimeNote() { return runtimeNote; },
        get ALLOWED_DOCUMENT_TYPES() { return ALLOWED_DOCUMENT_TYPES; },
        get DOCUMENT_EXTENSION_TYPES() { return DOCUMENT_EXTENSION_TYPES; },
        get clawFallbackCopy() { return clawFallbackCopy; },
      
  }, app)));
    }
    return coreModuleInstance;
  }
  // #7216 R5 step 1: the settings/sidebar modules own those sections. app.js keeps
  // one-line forwarders with the same names, so call sites and function-declaration
  // hoisting stay intact. deps getters/setters read the closure variables live, so a
  // value changed before the first call is still observed.
  // R5 B7: the settings module is on the registry — app.provide at the original
  // factory position (execution order kept); its API is reached through the
  // registry. selectedProductTier and closeSettings shadow the shared accessors
  // through the B6 allowlist (owner = this module).
  const settings = app.provide("settings",
    window.PadiemChatSettingsModule.create(Object.setPrototypeOf({

      get settingsDialog() { return settings.dom.settingsDialog; },

}, app)));
  function settingsModule() { return settings; }
  // R5 B7: the sidebar module is on the registry — app.provide at the original
  // factory position (execution order kept); its API is reached through the
  // registry instead of app.js one-line forwarders. closeSidebar shadows the
  // shared accessor through the B6 allowlist (owner = this module).
  const sidebar = app.provide("sidebar",
    window.PadiemChatSidebarModule.create(Object.setPrototypeOf({}, app)));
  function sidebarModule() { return sidebar; }
  // #7216 R5 step 2: the calendar module owns the Google Calendar READ pair.
  let calendarModuleInstance = null;
  function calendarModule() {
    if (!calendarModuleInstance) {
      calendarModuleInstance = app.provide("calendar", window.PadiemChatCalendarModule.create(Object.setPrototypeOf({

        get connectorsScope() { return connectors.connectorsScope; },
        // #7812 R5 B5: the Calendar READ state stays app.js-owned (in-session
        // grant truth), reached by the module only through this live pair.
        get googleCalendarReadState() { return googleCalendarReadState; },
        set googleCalendarReadState(value) { googleCalendarReadState = value; },
        get connectorTicketErrorKey() { return connectors.connectorTicketErrorKey; },
        get setConnectorCopy() { return connectors.setConnectorCopy; },
        get fetch() { return fetch; },
      
  }, app)));
    }
    return calendarModuleInstance;
  }
  // #7216 R5 step 3: the recent-conversations-menu module owns the history
  // list (rename/pin/delete) and the Claw recent-run presentation. app.js keeps
  // one-line forwarders with the same names. deps getters/setters read the closure
  // variables live, so a value changed before the first call is still observed.
  let historyModuleInstance = null;
  function historyModule() {
    if (!historyModuleInstance) {
      historyModuleInstance = app.provide("history", window.PadiemChatHistoryModule.create(Object.setPrototypeOf({

        get sidebarActionIcon() { return app.sidebarActionIcon; },
        get readClawRuns() { return app.readClawRuns; },
      
  }, app)));
    }
    return historyModuleInstance;
  }
  // #7216 R5: the auth module owns those sections. app.js keeps one-line
  // forwarders with the same names. deps getters/setters read the closure
  // variables live, so a value changed before the first call is still observed.
  let authModuleInstance = null;
  function authModule() {
    if (!authModuleInstance) {
      authModuleInstance = app.provide("auth", window.PadiemChatAuthModule.create(Object.setPrototypeOf({

        get accountAvatar() { return accountAvatar; },
        get accountDeleteActions() { return accountDeleteActions; },
        get accountPasswordActions() { return accountPasswordActions; },
        get accountSettingsSection() { return accountSettingsSection; },
        get settingsAccountEmail() { return settingsAccountEmail; },
        get advancedAccountSection() { return advancedAccountSection; },
        get applyAuthState() { return authModule().applyAuthState; },
        get clawApprovalSessionToken() { return clawApprovalSessionToken; },
        set clawApprovalSessionToken(value) { clawApprovalSessionToken = value; },
        get invalidateClawApprovalSession() { return authModule().invalidateClawApprovalSession; },
        get loginButton() { return loginButton; },
        get openClawRunTarget() { return navModuleInstance.openClawRunTarget; },
        get pendingNotificationConversationId() { return pendingNotificationConversationId; },
        set pendingNotificationConversationId(value) { pendingNotificationConversationId = value; },
        get pendingNotificationRunId() { return pendingNotificationRunId; },
        set pendingNotificationRunId(value) { pendingNotificationRunId = value; },
        get profilePanel() { return loginDialogModule().profilePanelElement(); },
        get resetAccountDeleteConfirm() { return accountModule().resetAccountDeleteConfirm; },
        get resolveSessionPresentation() { return authModule().resolveSessionPresentation; },
        get setLoginButtonCopy() { return authModule().setLoginButtonCopy; },
        get syncApprovedMemoryVisibility() { return app.syncApprovedMemoryVisibility; },
        get signOutCurrentAccount() { return authModule().signOutCurrentAccount; },
        get settingsLogoutButton() { return settingsLogoutButton; },
      
  }, app)));
    }
    return authModuleInstance;
  }
  // #7812 R5 B4-1: the account module owns password reset/change and account
  // deletion. Account-only DOM is looked up inside create() and the listeners
  // are registered by wireAccountControls().
  // R5 B7: the account module is on the registry — app.provide at the original
  // lazy factory position (creation timing kept); all 19 account names (the
  // password reset/change 12 and the account-deletion 7) are reached through
  // the registry instead of app.js one-line forwarders. The wire export is
  // named wireAccountControls because localPcPanel already owns the registry
  // name "wire".
  let accountModuleInstance = null;
  const accountModule = () => {
    if (!accountModuleInstance) {
      accountModuleInstance = app.provide("account", window.PadiemChatAccountModule.create(Object.setPrototypeOf({

        get passwordLoginContinue() { return loginDialogModule().emailContinueElement(); },
        get passwordAuthRequest() { return loginDialogModule().passwordAuthRequest; },
        get setAuthStatusMessage() { return loginDialogModule().setAuthStatusMessage; },
      
  }, app)));
    }
    return accountModuleInstance;
  };
  // #7216 R5: the conversation module owns those sections. deps getters/setters
  // read the closure variables live, so a value changed before the first call
  // is still observed.
  // R5 B7: the conversation module is on the registry — app.provide at the
  // original lazy factory position (creation timing kept); all 19 names (the
  // attachment chunk 8 and the remaining 11) are reached through the registry
  // instead of app.js one-line forwarders.
  let conversationModuleInstance = null;
  function conversationModule() {
    if (!conversationModuleInstance) {
      conversationModuleInstance = app.provide("conversation", window.PadiemChatConversationModule.create(Object.setPrototypeOf({

        get accountInitial() { return authModule().accountInitial; },
        get attachmentButton() { return attachmentButton; },
        get attachmentCapabilities() { return attachmentCapabilities; },
        get attachmentCountLimit() { return conversationModule().attachmentCountLimit; },
        get attachmentFileInput() { return attachmentFileInput; },
        get binaryDocuments() { return binaryDocuments; },
        get buildRetryBox() { return conversationModule().buildRetryBox; },
        get cancelStreamButton() { return cancelStreamButton; },
        get clearAttachment() { return conversationModule().clearAttachment; },
        get extensionOf() { return coreModule().extensionOf; },
        get failureStatusLabel() { return conversationModule().failureStatusLabel; },
        get form() { return form; },
        get formatBytes() { return coreModule().formatBytes; },
        get formatClockTime() { return coreModule().formatClockTime; },
        get readDocumentFile() { return coreModule().readDocumentFile; },
        get removeAttachmentItem() { return conversationModule().removeAttachmentItem; },
        get renderAttachmentChips() { return conversationModule().renderAttachmentChips; },
        get resetConversation() { return conversationModule().resetConversation; },
        get selectImage() { return coreModule().selectImage; },
        get sendButton() { return sendButton; },
        get switchConversationProduct() { return navModuleInstance.switchConversationProduct; },
      
  }, app)));
    }
    return conversationModuleInstance;
  }
  // #7216 R5 5b: the streaming section owns the async request lifetime.
  // R5 B7: the streaming module is on the registry — app.provide at the original
  // factory position (execution order kept); its API is reached through the
  // registry instead of app.js one-line forwarders.
  const streaming = app.provide("streaming",
    window.PadiemChatStreamingModule.create(Object.setPrototypeOf({

      get addAssistantShell() { return conversationModule().addAssistantShell; },
      get applyStreamDone() { return streaming.applyStreamDone; },
      get attachmentPayload() { return conversationModule().attachmentPayload; },
      get clawGeneralFailure() { return conversationModule().clawGeneralFailure; },
      get handleCustomRequestFailure() { return conversationModule().handleCustomRequestFailure; },
      get invalidateClawRunsRead() { return app.invalidateClawRunsRead; },
      get lifecycleForError() { return conversationModule().lifecycleForError; },
      get recoverStoredPcResult() { return pcRunModuleInstance.recoverStoredPcResult; },
      get renderAnswer() { return conversationModule().renderAnswer; },
      get renderCancelled() { return conversationModule().renderCancelled; },
      get renderError() { return conversationModule().renderError; },
      get renderTyping() { return historyModule().renderTyping; },
      get requestCompletedAnswer() { return streaming.requestCompletedAnswer; },
      get requestStreamingAnswer() { return streaming.requestStreamingAnswer; },
      get waitForAcceptedPcRun() { return pcRunModuleInstance.waitForAcceptedPcRun; },

}, app)));
  function streamingModule() { return streaming; }
  // #7216 R5 A3 (pc-run): PC execution polling, unfinished-run resume, and
  // durable PC result recovery live in chat-pc-run-module.js. app.js keeps
  // one-line forwarders and reads closure state live via getters.
  function pcRunModule() { return pcRunModuleInstance; }

  const shell = document.querySelector(".app-shell");
  const emptyState = document.getElementById("emptyState");
  const messageList = document.getElementById("messageList");
  // #3933 Hark WEB-FIRST: previous completed work files of the currently
  // displayed conversation, resolved only from the owner-scoped server index
  // (GET-only, no file bytes, no grant). Hidden until a verified reference
  // exists. The context module registers itself before this script runs.
  const conversationArtifacts = document.createElement("section");
  conversationArtifacts.id = "clawConversationArtifacts";
  conversationArtifacts.hidden = true;
  messageList.parentNode?.insertBefore(conversationArtifacts, messageList);
  const conversationArtifactContext =
    window.PadiemClawConversationArtifactContext?.init?.(conversationArtifacts) ?? null;
  const form = document.getElementById("composerForm");
  const input = document.getElementById("messageInput");
  // #6828: Claw runs on the chosen PADIEM grade. No model picker stays,
  // so no per-request model id is ever read from the DOM.
  const clawModelIdInput = null;
  const sendButton = document.getElementById("sendButton");
  const cancelStreamButton = document.getElementById("cancelStreamButton");
  const newChatButton = document.getElementById("newChatButton");
  settings.captureDialogElements();
  const accountSettingsSection = document.getElementById("accountSettingsSection");
  const settingsAccountEmail = document.getElementById("settingsAccountEmail");
  const advancedAccountSection = document.getElementById("advancedAccountSection");
  const accountPasswordActions = document.getElementById("accountPasswordActions");
  // #6659: account self-deletion. The server owns the authority and
  // the exact-email confirm; the browser only mirrors the same gate.
  const accountDeleteActions = document.getElementById("accountDeleteActions");
  const accountDeleteConfirm = document.getElementById("accountDeleteConfirm");
  const attachmentFileInput = document.getElementById("attachmentFileInput");
  const attachmentButton = document.getElementById("attachmentButton");
  const documentStarterButton = document.getElementById("documentStarterButton");
  const runtimeNote = document.getElementById("runtimeNote");
  const loginButton = document.getElementById("loginButton");
  const settingsLogoutButton = document.getElementById("settingsLogoutButton");
  const authDialog = document.getElementById("authDialog");
  let loginDialogModuleInstance = null;
  const loginDialogModule = () => {
    if (!loginDialogModuleInstance) {
      loginDialogModuleInstance = app.provide("loginDialog", window.PadiemChatLoginDialogModule.create(Object.setPrototypeOf({

        get googleLoginButton() { return googleLoginButton; },
        get passwordResetTokenFromLocation() { return accountModule().passwordResetTokenFromLocation; },
        get renderAndroidHandoff() { return androidHandoffModule().renderAndroidHandoff; },
        get isAndroidWebView() { return androidHandoffModule().isAndroidWebView; },
        get startAndroidHandoff() { return androidHandoffModule().startAndroidHandoff; },
      
  }, app)));
    }
    return loginDialogModuleInstance;
  };
  const googleLoginButton = document.getElementById("googleLoginButton");
  const androidHandoffPanel = document.getElementById("androidHandoffPanel");
  const androidHandoffCode = document.getElementById("androidHandoffCode");
  const androidHandoffNote = document.getElementById("androidHandoffNote");
  const androidHandoffOpen = document.getElementById("androidHandoffOpen");
  const androidHandoffCopy = document.getElementById("androidHandoffCopy");
  const androidHandoffCopied = document.getElementById("androidHandoffCopied");
  const androidHandoffCancel = document.getElementById("androidHandoffCancel");
  const androidHandoffError = document.getElementById("androidHandoffError");
  const passwordLoginForm = document.getElementById("passwordLoginForm");
  const authHandoff = document.getElementById("authHandoff");
  const passwordLoginIdentifier = document.getElementById("passwordLoginIdentifier");
  const passwordLoginPassword = document.getElementById("passwordLoginPassword");
  const passwordLoginError = document.getElementById("passwordLoginError");
  const passwordLoginSubmit = document.getElementById("passwordLoginSubmit");
  const passwordRegisterSection = document.getElementById("passwordRegisterSection");
  const passwordRegisterForm = document.getElementById("passwordRegisterForm");
  const passwordRegisterEmail = document.getElementById("passwordRegisterEmail");
  const passwordRegisterName = document.getElementById("passwordRegisterName");
  const passwordRegisterPassword = document.getElementById("passwordRegisterPassword");
  const passwordRegisterError = document.getElementById("passwordRegisterError");
  const passwordRegisterSubmit = document.getElementById("passwordRegisterSubmit");
  // #5481: the lost-password entry. The forgot-password link opens the reset
  // request view, and the one-time link the server mails opens the reset
  // confirm view directly.
  const passwordResetOpen = document.getElementById("passwordResetOpen");
  const passwordResetPanel = document.getElementById("passwordResetPanel");
  const passwordResetRequestView = document.getElementById("passwordResetRequestView");
  const passwordResetConfirmView = document.getElementById("passwordResetConfirmView");
  const passwordResetEmail = document.getElementById("passwordResetEmail");
  const passwordResetRequestError = document.getElementById("passwordResetRequestError");
  const passwordResetRequestStatus = document.getElementById("passwordResetRequestStatus");
  const passwordResetNew = document.getElementById("passwordResetNew");
  const passwordResetConfirmError = document.getElementById("passwordResetConfirmError");
  const passwordResetConfirmStatus = document.getElementById("passwordResetConfirmStatus");
  const accountName = document.getElementById("accountName");
  const accountAvatar = document.getElementById("accountAvatar");
  const accountContainer = document.querySelector(".sidebar-account");
  // Presentation-only account summary. The canonical login/logout button stays
  // visible and retains its existing auth guards and keyboard contract.
  const profileToggle = document.createElement("button");
  profileToggle.type = "button";
  profileToggle.id = "accountProfileButton";
  profileToggle.className = "account-profile-toggle";
  profileToggle.setAttribute("aria-controls", "settingsDialog");
  profileToggle.setAttribute("aria-haspopup", "dialog");
  profileToggle.setAttribute("aria-expanded", "false");
  profileToggle.dataset.localeAriaLabel = "account-profile-toggle";
  profileToggle.setAttribute("aria-label", coreModule().uiT("account-profile-toggle"));
  // Some auth fixtures mount account controls without the original avatar as a
  // direct child; prepend never assumes a particular descendant relationship.
  accountContainer?.prepend(profileToggle);
  // Keep #accountAvatar and #accountName as direct accountContainer children:
  // product-capabilities.js rehomes fallback avatars before the account name.
  // A separate accessible button overlays those text/visual nodes instead.
  const historySection = document.getElementById("historySection");
  const historyList = document.getElementById("historyList");
  const historyActionStatus = document.getElementById("historyActionStatus");
  const historyEmpty = document.getElementById("historyEmpty");
  // #7812 R5 B7: the project list, dialogs and project-file controls are created
  // here at the original declaration position. Shared selection state lives in the Context.
  const projectModule = app.provide("project",
    window.PadiemChatProjectModule.create(Object.setPrototypeOf({

      get binaryDocuments() { return binaryDocuments; },
      get failureCodeNote() { return conversationModule().failureCodeNote; },
      get fetch() { return fetch.bind(window); },

    }, app)));
  projectModule.mountProjectControls();
  const chatTransport = window.PadiemChatTransport;
  const conversationState = window.PadiemChatConversationState;
  // #2505: Chat(B62) and Claw(B54) are two screens of one product and share one
  // conversation: one rendered transcript, one conversation id, one skill. A
  // product switch only changes the lane the NEXT submit belongs to, so a
  // thread started on one screen continues on the other. Nothing is moved or
  // deleted here: the server-owned conversation record stays untouched.
  const PRODUCT_CHAT = "chat";
  const PRODUCT_CLAW = "claw";

  let conversationProduct = PRODUCT_CHAT;
  // The Claw artifact index belongs to one Claw conversation only. The owner
  // conversation id it was last requested for is remembered so a product
  // switch never repeats the same read.
  let clawArtifactShownFor = "";
  const MESSAGE_LIFECYCLE = window.PadiemChatLifecycle.states;
  const attachmentCapabilities = window.PadiemAttachmentCapabilities;
  const binaryDocuments = window.PadiemBinaryDocuments;

  const ALLOWED_IMAGE_TYPES = new Set(attachmentCapabilities.images.flatMap((format) => format.mediaTypes));
  const ALLOWED_DOCUMENT_TYPES = new Set(attachmentCapabilities.textDocuments.flatMap((format) => format.mediaTypes));
  const DOCUMENT_EXTENSION_TYPES = new Map(
    attachmentCapabilities.textDocuments.flatMap((format) => format.extensions.map((extension) => [extension, format.mediaTypes[0]]))
  );

  let inFlight = false;
  let activeRequestController = null;
  let activeRequestArticle = null;
  let activeRequestCancelReason = null;
  // #6460 step 3: the server run id of the live Claw turn, when the transport
  // reported one. Pressing the composer stop button sends it to the server
  // stop route, which records the stop time and refuses any PC action created
  // after it.
  let activeClawRunId = null;
  // Latest successfully completed answer request, for the one-click
  // regenerate action. Replays through requestAnswer with the exact stored
  // routing snapshot, so model lane, tier, auth and approval conditions are
  // identical to the original send. Cleared on conversation reset.
  let lastCompletedAnswerRequest = null;
  let conversationEpoch = 0;
  // #261102 multi-attachment: the attachment chip list one message carries.
  // Each chip holds its own rejection state; only valid chips reach the
  // send payload.
  let selectedAttachments = [];
  // Only the owner-scoped Claw run history can identify a Claw thread.
  const clawConversationIds = new Set();
  let clawConversationLabelsRead = null;

  // Android 1.0.0 keeps chat.padiem.net in a WebView and completes Google in a
  // Custom Tab whose cookies never reach the WebView. The WebView therefore
  // creates a one-time handoff and claims it with a secret held only in this
  // tab's temporary storage — never in a URL and never in durable storage.
  const ANDROID_HANDOFF_STORAGE_KEY = "padiem.androidHandoff.v1";
  const ANDROID_HANDOFF_POLL_MS = 2000;
  let androidHandoff = null;
  let androidHandoffTimer = null;
  let androidHandoffClaiming = false;
  let androidHandoffStarting = false;

  // Short-lived overlay, not a new composer row.
  window.addEventListener("padiem:composer-hint", (event) => {
    if (event && event.detail && typeof event.detail.key === "string") {
      conversationModule().showComposerInlineHint(event.detail.key);
    }
  });
  sendButton.addEventListener("click", () => {
    // #5561: an empty composer shows the voice waveform, so the empty-message
    // notice belongs to the send arrow only.
    if (window.PadiemVoiceMenu?.isVoicePrimaryAction?.()) return;
    if (!input.value.trim() && !inFlight) conversationModule().showComposerInlineHint("composer-empty-message");
  });

  // #4862: Claw is a restorable product route, exactly like Automation.
  // The fragment names the destination only. It never carries a user id,
  // session token or conversation id, so a reload after logout or an account
  // switch can at most reopen the Claw shell for the current session, which
  // renders from the current session's own server-side state.
  const AUTOMATION_ROUTE_HASH = "#padiem-automation";
  const CLAW_ROUTE_HASH = "#padiem-claw";
  // #5895/2026-11-01: the council app's connect-computer button lands on the
  // existing Connectors surface. The fragment is a destination only — no
  // pairing, device or session value rides it.
  const CONNECTORS_ROUTE_HASH = "#padiem-connectors";
  // 11-03 audit: Calendar, Library and Meeting were reachable only by clicking
  // the menu, so their URL kept whatever fragment the previous screen had left
  // behind — Library and Calendar both showed #padiem-automation and the
  // meeting notes had no fragment at all. Each screen now names itself the way
  // the three routes above already do: a destination only, no id or token.
  const CALENDAR_ROUTE_HASH = "#padiem-calendar";
  const LIBRARY_ROUTE_HASH = "#padiem-library";
  const MEETING_ROUTE_HASH = "#padiem-meeting";
  // The full-screen settings page the compact modal links to. The fragment
  // is a destination only, exactly like the three panel routes.
  const ADVANCED_SETTINGS_ROUTE_HASH = "#padiem-settings";
  let automationDestinationReady = false;
  // #7216 R5 A10 (nav) / R5 part 2 B2-4: the screen-switch section — the page
  // contract table, the route-fragment table, the URL fragment rules,
  // setNavActive, the Chat|Claw product switch and the Claw/Chat workspace
  // entries — lives in chat-nav-module.js, which is created here, at the
  // original declaration position (the Claw navigation lookup keeps the same
  // boot order). app.js keeps the shared route fragments, the two window
  // contracts, one-line forwarders and wire calls at the original listener
  // positions.
  const navModuleInstance = app.provide("nav", window.PadiemChatNavModule.create(Object.setPrototypeOf({

        get AUTOMATION_ROUTE_HASH() { return AUTOMATION_ROUTE_HASH; },
        get CLAW_ROUTE_HASH() { return CLAW_ROUTE_HASH; },
        get CONNECTORS_ROUTE_HASH() { return CONNECTORS_ROUTE_HASH; },
        get CALENDAR_ROUTE_HASH() { return CALENDAR_ROUTE_HASH; },
        get LIBRARY_ROUTE_HASH() { return LIBRARY_ROUTE_HASH; },
        get MEETING_ROUTE_HASH() { return MEETING_ROUTE_HASH; },
        get ADVANCED_SETTINGS_ROUTE_HASH() { return ADVANCED_SETTINGS_ROUTE_HASH; },
        get automationDestinationReady() { return automationDestinationReady; },
        get syncComposerForClaw() { return clawStatusModule().syncComposerForClaw; },
        get app() { return app; },
  
   }, app)));
   window.PadiemChatRouting = Object.freeze({ syncRouteHash: navModuleInstance.syncRouteHash });
  // The first user turn extends the original landing panel. Older saved
  // threads still open directly on messages instead of replaying the hero.
  /* Owner 2026-10-20: the user avatar shows the first character of the
   * signed-in account name. The name -> avatar order is unchanged and the
   * initial is read from the live account display name, never hardcoded. */

  /* One clock format for both turns: the user turn and the answer row. */

  // The runtime status chip has one owner (message-lifecycle.js). A finished
  // answer releases the "answer preparing" chip, and a real status (a Claw P01
  // stage, a failure) is never removed by accident. The calls go through the
  // global because a single-function harness evaluates this file's function in
  // a bare scope.
  // #3936/#3933: a model HOLD is a bounded refusal raised BEFORE dispatch, so it
  // must not wear the generic "this run may already have started" state. Closed
  // code→copy map only: a raw server, Engine or provider string is never shown.
  // Closed server code for a rejected customer-owned key. Named here so the
  // streaming answer region keeps no provider vocabulary of its own.
  // #3933: ONE lookup for every Claw failure surface. The composer lane, the live
  // SSE lane and the manual-intake lane all resolve the same server code through
  // this function, so a bounded refusal can never render two different sentences
  // or drift into a second invented copy. `Object.hasOwn` only: an inherited or
  // spoofed key never selects copy, and an unlisted code returns null so each
  // caller keeps its own existing fallback.
  // #5568: one bounded reason line under a Chat failure. Only the server's
  // compact code identifier is rendered; the message copy stays server/locale
  // authored. Claw keeps its existing refusal/recovery presentation, and an
  // unexpected string is never echoed into the notice.

  // #5479: one presentation rule for every session state, so the sign-in entry
  // point can never disappear just because the session state could not be read.
  //
  // "pending" is "not read yet". "unavailable" is the server's own word: it
  // answered that the session store is not ready, so there is nothing to sign
  // into and the account area stays hidden (the reviewed contract the account
  // session browser QA pins). "unreachable" is the status request producing no
  // answer at all: a network failure, or the Chat Worker failing to start a
  // Python instance (the platform's NoGilError race, cloudflare/workerd#6624),
  // which turns every route - /api/auth/status included - into a 5xx. That is
  // not a signed-out account and not a server verdict, so it must not remove
  // the only way to obtain a session: the account area and the login button
  // stay visible and enabled, and the button retries the status instead of
  // being a dead end.
  //
  // The table is the rule: the projections read it, and the #5479 regression
  // test reads the same table out of this file.
  // The other projections read the same rule so they cannot drift apart.
  window.PadiemSessionPresentation = authModule().resolveSessionPresentation;

  // #5034: a Web Push click can be a cold start, so the run reference arrives in
  // the URL before any view exists. The query carries only the server-derived
  // occurrence id — no title, no document, no secret. It is consumed once, only
  // after the session proves this owner, and it opens the SAME run target the
  // calendar link-back already owns instead of a second navigation authority.
  const NOTIFICATION_RUN_REF = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
  let pendingNotificationRunId = "";
  {
    // Parsed with the plain-split shape the connector return already uses: this
    // file is also loaded inside curated VM harnesses that do not define the
    // query-string helper, and a percent-escaped reference fails the grammar
    // above rather than being decoded into a target.
    const notificationParts = String((window.location && window.location.search) || "")
      .replace(/^\?/, "").split("&");
    const runPart = notificationParts.find((part) => part.startsWith("run_id=")) || "";
    if (notificationParts.indexOf("notify=run") >= 0
        && NOTIFICATION_RUN_REF.test(runPart.slice("run_id=".length))) {
      pendingNotificationRunId = runPart.slice("run_id=".length);
    }
  }

  // Owner decision 2026-11-07: an automation notification click opens the
  // automation's own conversation — one rule owns one conversation, and the
  // query carries the server-derived chat_ id only, consumed once after the
  // session proves the owner. The id must be the exact conversation grammar;
  // anything else is left in the URL untouched rather than decoded into a
  // target.
  const NOTIFICATION_CONVERSATION_ID = /^chat_[a-f0-9]{32}$/;
  let pendingNotificationConversationId = "";
  {
    const conversationParts = String((window.location && window.location.search) || "")
      .replace(/^\?/, "").split("&");
    const conversationPart = conversationParts.find((part) => part.startsWith("conversation_id=")) || "";
    if (conversationParts.indexOf("notify=conversation") >= 0
        && NOTIFICATION_CONVERSATION_ID.test(conversationPart.slice("conversation_id=".length))) {
      pendingNotificationConversationId = conversationPart.slice("conversation_id=".length);
    }
  }



  // #7216 R5 A6 (android-handoff): start/claim/poll and the handoff panel live
  // in chat-android-handoff-module.js. app.js keeps the declarations, the
  // session-storage reader/writer and resumeAndroidHandoff (R-06).
  // R5 B7 round 20: the module is on the registry — app.provide inside the original
  // lazy factory (creation timing kept: first call is the wire at boot); the
  // 9 names are reached through the registry instead of app.js forwarders.
  let androidHandoffModuleInstance = null;
  function androidHandoffModule() {
    if (!androidHandoffModuleInstance) {
      androidHandoffModuleInstance = app.provide("androidHandoff", window.PadiemChatAndroidHandoffModule.create(Object.setPrototypeOf({

        get androidHandoff() { return androidHandoff; },
        set androidHandoff(value) { androidHandoff = value; },
        get androidHandoffTimer() { return androidHandoffTimer; },
        set androidHandoffTimer(value) { androidHandoffTimer = value; },
        get androidHandoffClaiming() { return androidHandoffClaiming; },
        set androidHandoffClaiming(value) { androidHandoffClaiming = value; },
        get androidHandoffStarting() { return androidHandoffStarting; },
        set androidHandoffStarting(value) { androidHandoffStarting = value; },
        get androidHandoffPanel() { return androidHandoffPanel; },
        get androidHandoffCode() { return androidHandoffCode; },
        get androidHandoffNote() { return androidHandoffNote; },
        get androidHandoffOpen() { return androidHandoffOpen; },
        get androidHandoffCopy() { return androidHandoffCopy; },
        get androidHandoffCopied() { return androidHandoffCopied; },
        get androidHandoffCancel() { return androidHandoffCancel; },
        get androidHandoffError() { return androidHandoffError; },
        get ANDROID_HANDOFF_POLL_MS() { return ANDROID_HANDOFF_POLL_MS; },
        get storeAndroidHandoff() { return storeAndroidHandoff; },
      
  }, app)));
    }
    return androidHandoffModuleInstance;
  }


  function readStoredAndroidHandoff() {
    try {
      const raw = window.sessionStorage.getItem(ANDROID_HANDOFF_STORAGE_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") return null;
      if (typeof parsed.handoffId !== "string" || !/^aho_[A-Za-z0-9_-]{20,48}$/.test(parsed.handoffId)) return null;
      if (typeof parsed.claimSecret !== "string" || parsed.claimSecret.length < 16 || parsed.claimSecret.length > 128) return null;
      if (typeof parsed.userCode !== "string" || !/^[A-Z2-9]{4}-[A-Z2-9]{4}$/.test(parsed.userCode)) return null;
      if (typeof parsed.authorizationUrl !== "string" || !/^https:\/\//.test(parsed.authorizationUrl)) return null;
      if (!Number.isFinite(parsed.expiresAt)) return null;
      return parsed;
    } catch (_) {
      return null;
    }
  }

  function storeAndroidHandoff() {
    try {
      if (androidHandoff) {
        window.sessionStorage.setItem(ANDROID_HANDOFF_STORAGE_KEY, JSON.stringify(androidHandoff));
      } else {
        window.sessionStorage.removeItem(ANDROID_HANDOFF_STORAGE_KEY);
      }
    } catch (_) {
      // Storage can be unavailable in hardened WebViews; the in-memory flow still works.
    }
  }









  function resumeAndroidHandoff() {
    if (!androidHandoffModule().isAndroidWebView()) return;
    const stored = readStoredAndroidHandoff();
    if (!stored) return;
    if (Date.now() >= stored.expiresAt) {
      try { window.sessionStorage.removeItem(ANDROID_HANDOFF_STORAGE_KEY); } catch (_) {}
      return;
    }
    if (stored.phase === "claiming") stored.phase = "waiting";
    androidHandoff = stored;
    androidHandoffModule().renderAndroidHandoff();
    androidHandoffModule().startAndroidHandoffPolling();
    androidHandoffModule().pollAndroidHandoff();
  }

  // #5481: the lost-password flow. The entry link opens the request view, the
  // mailed one-time link opens the confirm view. The token never travels in
  // a query string: it arrives in the URL fragment, which the browser does
  // not send to the server.
  // A LoveTree sign-in ticket read from the address bar. Same shape and same
  // caution as the reset-link read below: the app shell also loads inside
  // curated VM harnesses without a location object, so this runs when the
  // dialog opens, never at load time. No wording or layout changes.

  // #6659: the usage guide offers example sentences as ./?say=<text>. One press
  // brings the words here, typed but unsent, on the screen the person already
  // uses. Read once at load like the reset link below, and the address is
  // cleaned so a refresh cannot re-type over what the person has since written.
  function examplePromptFromLocation() {
    try {
      const raw = window.location.search || "";
      const match = /[?&]say=([^&]{1,2048})(?:&|$)/.exec(raw);
      if (!match) return "";
      return String(decodeURIComponent(match[1].replace(/\+/g, " "))).slice(0, 400);
    } catch (_) {
      return "";
    }
  }

  // #7812 R5 B3 (rule (b), R-11): the module registers the recent-menu click and
  // Escape listeners at this original position, so their order among the other
  // document listeners is unchanged.
  historyModule().wireMenuListeners();
  // #7175: the server owns both the title and the pin. The sidebar only sends
  // the two reviewed fields and then re-reads the owner-scoped list, so the
  // group order and every label come from the same answer.

  // #7812 R5 B4-2 (rule (b)): the auth module registers the session-refresh
  // listener at this original position, keeping its document order.
  authModule().wireSessionRefresh();

  const entry = app.provide("entry", window.PadiemChatEntryModule.create(app));

  // #4471: the sidebar conversation search opens a hit through this loader
  // instead of a recent-list DOM row, so a hit outside the recent page still
  // restores with the same auth guard, inFlight lock, project restore and the
  // server-verified Claw set. Read-only handle: it grants no new authority.
  window.PadiemChatConversationOpener = Object.freeze({
    open: (conversationId) => entry.openSavedConversation(conversationId),
  });

  // #4489: the Library opens a stored project file through that file's owning
  // project in the existing Project dialog, so project-file permission, the
  // files panel and every edit guard stay on the one canonical path. The project
  // resolves from the owner list or its existing authenticated project lookup;
  // a foreign or stale id opens nothing. This handle grants no new authority.
  window.PadiemChatProjectOpener = Object.freeze({
    openFile: projectModule.openFile,
    open: projectModule.open,
  });

    // Hark's private web XLSX intake creates a separate trusted owner-owned
  // work conversation. This explicit navigation never guesses that it was the
  // currently displayed chat or fabricates an assistant answer/file READ grant.
  window.addEventListener("padiem:claw-web-work-conversation-open", async (event) => {
    const detail = event?.detail;
    if (!app.authState.authenticated || inFlight || !detail
        || typeof detail.conversationId !== "string"
        || !/^chat_[a-f0-9]{32}$/.test(detail.conversationId)) return;
    // Two server-verified handoff shapes exist: an exact owner-indexed
    // artifact reference (completed revision) or a conversation-only handle
    // for the verified owner workcopy. A partial artifact reference is
    // refused instead of being treated as verified, and neither shape is a
    // new file READ/WRITE grant.
    const hasArtifact = detail.artifactId !== undefined
      || detail.integrityRef !== undefined;
    if (hasArtifact
        && !(typeof detail.artifactId === "string"
             && /^doc_[a-f0-9]{32}$/.test(detail.artifactId)
             && typeof detail.integrityRef === "string"
             && /^[a-f0-9]{64}$/.test(detail.integrityRef))) return;
    // The work conversation is loaded through the existing authenticated,
    // owner-scoped /api/conversations/:id endpoint. The XLSX UI separately
    // confirmed the exact owner-scoped artifact GET before raising an
    // artifact-bearing event, and the owner workcopy status read for the
    // conversation-only one.
    const opened = await entry.openSavedConversation(detail.conversationId);
    if (!opened) return;
    const notice = document.createElement("p");
    notice.className = "reference-note";
    notice.setAttribute("role", "status");
    notice.textContent = coreModule().uiT(hasArtifact
      ? "claw-web-work-conversation-opened"
      : "claw-web-work-conversation-opened-read");
    messageList.prepend(notice);
    coreModule().setNote(coreModule().uiT("claw-web-work-conversation-note"));
  });

  // R5 B7: requestCompletedAnswer·applyStreamDone are on the registry
  // (provide("streaming")).

  // Transport completion does not imply a completed durable PC run. R5 part 2
  // B2: resolvedPcRuns and pcResultRecovery are owned by chat-pc-run-module.js,
  // which is created here, at the original declaration position.
  const pcRunModuleInstance = app.provide("pcRun", window.PadiemChatPcRunModule.create(Object.setPrototypeOf({

    get findUnfinishedPcRun() { return pcRunModuleInstance.findUnfinishedPcRun; },
    get pcWaitElapsed() { return pcRunModuleInstance.pcWaitElapsed; },
    get renderStoredPcAnswer() { return pcRunModuleInstance.renderStoredPcAnswer; },
    get showPcRuntimeStatus() { return pcRunModuleInstance.showPcRuntimeStatus; },
  
  }, app)));

  // R5 B7: requestStreamingAnswer·cancelActiveStream are on the registry
  // (provide("streaming")).

  // #4317: product-capabilities.js is loaded AFTER app.js and owns the tier
  // state. The universally available signed-in Free lane stays the default for
  // an account that never chose a tier.
  // #5222: an account that DID choose a tier keeps that choice across a
  // reload, so this page must not reset the selection to Free behind the
  // account's back. The restored value is always re-validated by the server
  // (member grade + administrator gate) before it is used.

  // #7216 R5 step 1: chat-settings-module.js owns the settings section body.
  // R5 B7: selectedProductTier is on the registry (provide("settings")).
  // A failed PADIEM Custom request that needs the customer's key reopens the
  // existing model card. No second dialog and no generic fallback to a PADIEM
  // tier: the server's error message stays in the answer bubble.

  // R5 B7: requestAnswer is on the registry (provide("streaming")).
  // #3539: the generic B54 Claw composer runs on the canonical P01 Engine lane.
  // This predicate documents the product state that selects the lane: the Claw
  // shell with the explicit manual form hidden. It must be read at submit time,
  // BEFORE any conversation presentation transition.

  // One-click answer regenerate for the action bar (outputs.js). Only the
  // latest completed answer may regenerate: the stored article, lifecycle
  // state and DOM position are all re-verified, and requestAnswer's inFlight
  // lock rejects any overlapping second call, so no duplicate or unintended
  // paid model call can fire. No user bubble is added; the same outbound
  // messages replay through the identical routing path.
  window.PadiemChatRegenerate = Object.freeze({
    available(article) {
      return entry.storedRegenerateRequest(article) !== null;
    },
    regenerate(article) {
      const stored = entry.storedRegenerateRequest(article);
      if (!stored) return false;
      void streaming.requestAnswer(stored.outboundMessages, stored.skill, stored.attachment, stored.contextSnapshot, stored.clawGeneralRequest);
      return true;
    },
  });

  // Owner decision 2026-11-05: Chat/Claw AI answers are signed-in only.
  // The composer stays editable; pressing send opens the existing login
  // dialog, keeps the typed text, and never leaves a model request behind.
  // The server is the final authority and answers a bypassing guest with 401
  // login_required. A mock/preview deployment that cannot authenticate keeps
  // its CI harness behavior through the server-owned flag.


  // R5 B7: openSettings·closeSettings·openAdvancedSettingsView·
  // closeAdvancedSettingsView are on the registry (provide("settings")).
  settings.captureAdvancedView();
  // The full page opens on top of the screen the user came from (home, chat or
  // claw). Its back entry must return there instead of assuming home.
  // #7812 R5 B5 (rule (b)): settings module registers this at the original spot.
  settingsModule().wireTierChange();
  conversationModule().wireComposerEvents({ submitPrompt: entry.submitPrompt, cancelActiveStream: streaming.cancelActiveStream, documentStarterButton });
  projectModule.wireProjectListeners();
  // #5560: one sign-out implementation, reached from the sidebar session
  // button and from Settings > Account. The server session invalidation and
  // the local conversation reset are the same in both paths.
  loginDialogModule().wireGuestLogin();
  authModule().wireLoginButton();
  // #7812 R5 B5 (rule (b)): the settings module registers the advanced-settings
  // click/Escape listeners at this original block.
  settingsModule().wireAdvancedSettings();
  settingsModule().wireAdvancedMenuListeners();
  authModule().wireLogoutButton();
  loginDialogModule().wireDialogClose();
  loginDialogModule().wireGoogleLogin();
  androidHandoffModule().wireAndroidHandoffListeners();
  // #7812 R5 B4-1 (rule (b)): the module registers the reset/change/delete
  // listeners at this original position, so their registration order is unchanged.
  accountModule().wireAccountControls();
  document.querySelectorAll("[data-prompt]").forEach((button) => button.addEventListener("click", () => {
    entry.submitPrompt(button.dataset.prompt || "", button.dataset.skill || "auto");
    sidebar.closeSidebar();
  }));
  newChatButton.addEventListener("click", () => conversationModule().resetConversation(true));
  // The visible account name/avatar is the one-step Settings entry.
  // Reuse the existing settings action; do not create a second settings flow.
  loginDialogModule().wireProfileToggle();
  loginDialogModule().wireProfileSettings();
  loginDialogModule().wireProfileDismiss();
  settingsModule().wireSettingsDialog();
  sidebar.wireSidebarListeners();
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !loginDialogModule().profilePanelElement().hidden) {
      authModule().closeProfilePanel(true);
      return;
    }
    if (event.key === "Escape" && shell.classList.contains("sidebar-open")) sidebar.closeSidebar();
  });
  window.addEventListener("padiem:localechange", () => {
    authModule().applyAuthState(app.authState);
    androidHandoffModule().renderAndroidHandoff();
    navModuleInstance.setNavActive();
    if (app.projectsReady) projectModule.renderProjects();
    projectModule.renderProjectState();
    if (!selectedAttachments.length) coreModule().setNote(coreModule().idleNote());
    clawStatusModule().syncComposerForClaw(shell.dataset.state === "claw");
      });
  window.addEventListener("padiem:attachmentcapabilitychange", () => {
    if (!selectedAttachments.length) coreModule().setNote(coreModule().idleNote());
  });

  // Claw first-class workspace & MVP usability wiring (#2299)
  const clawWorkspace = document.getElementById("clawWorkspace");
  // R5 B1: the automation modules own their declarations (rule (a)) and are
  // created here, at the original declaration position (lookup timing kept).
  const automation = app.provide("automation",
    window.PadiemChatAutomationModule.create(app));
  const automationForm = app.provide("automationForm",
    window.PadiemChatAutomationFormModule.create(app));
  const clawManualForm = document.getElementById("clawManualForm");
  const clawChannel = document.getElementById("clawChannel");
  const clawAction = document.getElementById("clawAction");
  const clawSender = document.getElementById("clawSender");
  const clawResultArea = document.getElementById("clawResultArea");
  const clawResultPreview = document.getElementById("clawResultPreview");
  const clawResultCard = document.getElementById("clawResultCard");
  const clawResultEmpty = document.getElementById("clawResultEmpty");
  // R5 part 2 B2: the result-surface declarations only this module uses are
  // owned by chat-claw-run-module.js, which is created here, at the original
  // declaration position.
  // R5 B7: the clawRun module is on the registry — app.provide at the original
  // factory position (execution order kept); its API is reached through the
  // registry instead of app.js one-line forwarders.
  const clawRun = app.provide("clawRun",
    window.PadiemChatClawRunModule.create(Object.setPrototypeOf({

    get clawResultBadge() { return clawResultBadge; },
    get clawBoundedRefusalCopy() { return conversationModule().clawBoundedRefusalCopy; },
    get approvalDecisionErrorMessage() { return conversationModule().approvalDecisionErrorMessage; },
        get loadClawRunHistory() { return runHistory.loadClawRunHistory; },
    get clawRetryRemaining() { return clawStatusModule().clawRetryRemaining; },
    get clawCurrentDispatchIsUncertain() { return clawStatusModule().clawCurrentDispatchIsUncertain; },
    get clawVisibleExecutePayload() { return clawStatusModule().clawVisibleExecutePayload; },
    get clawExecuteWireKey() { return clawStatusModule().clawExecuteWireKey; },
    get clawRetryAfterFromResponse() { return clawStatusModule().clawRetryAfterFromResponse; },
    get isAmbiguousClawFailure() { return clawStatusModule().isAmbiguousClawFailure; },
    get beginClawRetryCooldown() { return clawStatusModule().beginClawRetryCooldown; },
    get showClawAmbiguousRecoveryHint() { return clawStatusModule().showClawAmbiguousRecoveryHint; },
    get beginClawWait() { return clawStatusModule().beginClawWait; },
    get app() { return app; },

  }, app)));
  // R5 part 2 B2: the declarations only this module uses (the generate/retry/wait
  // DOM refs, retry and wait timers, and the uncertainty set) are owned by
  // chat-claw-status-module.js, which is created here, at the original
  // declaration position.
  // R5 B7: the clawStatus module is on the registry — app.provide at the
  // original factory position (execution order kept); its retry/recovery/wait
  // API is reached through the registry instead of app.js one-line forwarders.
  const clawStatusModuleInstance = app.provide("clawStatus",
    window.PadiemChatClawStatusModule.create(Object.setPrototypeOf({

    get clawStatus() { return clawStatus; },
    get clawRetryBox() { return clawRetryBox; },
    get clawRetryHint() { return clawRetryHint; },
    get clawWaitStartedAt() { return clawWaitStartedAt; },
    set clawWaitStartedAt(value) { clawWaitStartedAt = value; },
    get localeOr() { return coreModule().localeOr; },

  }, app)));
  const clawExecuteButton = document.getElementById("clawExecuteButton");
  const clawResultBadge = document.getElementById("clawResultBadge");
  const clawResultDocx = document.getElementById("clawResultDocx");
  const clawStatus = document.getElementById("clawStatus");
  const clawRetryBox = document.getElementById("clawRetryBox");
  const clawRetryButton = document.getElementById("clawRetryButton");
  const clawRetryHint = document.getElementById("clawRetryHint");
  const clawResultHint = document.getElementById("clawResultHint");
  const clawExecuteHint = document.getElementById("clawExecuteHint");

  let clawInFlight = false;
  const clawForm = app.provide("clawForm",
    window.PadiemChatClawFormModule.create(Object.setPrototypeOf({
      get clearClawArtifact() { return clawRun.clearClawArtifact; },
      get renderClawRequestEcho() { return clawRun.renderClawRequestEcho; },
      get revealClawCard() { return clawRun.revealClawCard; },
      get runClawExecution() { return clawRun.runClawExecution; },
      get noteClawContentEdited() { return clawStatusModule().noteClawContentEdited; },
      get app() { return app; },
    }, app)));
  clawForm.initializeAction(clawAction?.value || "quote");
  let clawLastDispatchKey = "";
  // In-flight elapsed wait state (#2763). Owned by the wait block below.
  let clawWaitStartedAt = 0;
  let clawApprovalInFlight = false;
  // #4488 re-login: monotonic session generation for the pending-approval
  // decision surface. A decision captures this value when it starts; losing
  // the session (or signing in as a different account) bumps it, so a response
  // that lands after the transition can neither repaint the signed-out surface
  // nor resurrect a previous session's run state. Same shape as the
  // run-history visibility epoch.
  let clawApprovalEpoch = 0;
  // Best-effort client-visible session identity. The browser holds no stable
  // user id, so the account display name is the only switch signal available.
  let clawApprovalSessionToken = "unset";


  const clawFallbackCopy = {
    "claw-result-badge": "Preview",
    "claw-result-badge-run": "Real run",
    "claw-status-preview-running": "Generating preview...",
    "claw-status-execute-running": "Running... please wait a moment.",
    "claw-status-preview-success": "Preview is ready.",
    "claw-status-execute-success": "Done.",
    "claw-wait-elapsed": "Elapsed {seconds}s",
    "claw-wait-long": "Still running. The result will appear here when it is ready.",
    "claw-wait-very-long": "This is taking longer than usual. The request is still running and nothing is sent twice.",
    "claw-error-preview": "Preview could not be loaded. Please try again shortly.",
    "claw-error-empty": "Paste your request before running.",
    "claw-error-too-large": "Request is too long. Please shorten it and try again.",
    "claw-error-invalid": "Please check your input and try again.",
    "claw-error-rate-limited": "Too many requests right now. Please try again shortly.",
    "claw-btn-retry": "Try again",
    "claw-retry-waiting": "Requests are temporarily limited. You can try again in {seconds}s. Nothing is sent automatically.",
    "claw-retry-ready": "You can try again now. Sending uses what is currently in the form.",
    "claw-error-check-runs": "A run may already have started. Nothing was re-run automatically — check Recent runs first.",
    "claw-error-auth-needed": "Please sign in again to continue.",
    "claw-error-auth-unavailable": "This feature isn't available because the workspace sign-in state can't be verified. Please check the workspace configuration.",
    "claw-error-storage": "Could not save the document. Please try again shortly.",
    "claw-error-generic": "Something went wrong. Please try again shortly.",
    "claw-memory-review-title": "Memory save proposal (approval required)",
    "claw-memory-approve": "Approve",
    "claw-memory-reject": "Reject",
    "claw-memory-detail": "Details",
    "claw-memory-close": "Close",
    "claw-memory-type": "Type",
    "claw-memory-name": "Name",
    "claw-memory-note": "Note",
    "claw-memory-channel": "Channel",
    "claw-memory-status": "Status",
    "claw-memory-created": "Created",
    "claw-memory-updated": "Updated",
    "claw-memory-status-approved": "Approved",
    "claw-memory-error-approval": "Explicit approval is required.",
    "claw-memory-error-invalid": "The proposal format is invalid.",
    "claw-memory-error-auth": "Please sign in.",
    "claw-memory-error-unavailable": "Approved memory is unavailable.",
    "claw-memory-error-not-found": "Memory was not found.",
    "claw-memory-error-generic": "Approved memory could not be processed.",
    "claw-runs-title": "Recent runs",
    "claw-runs-empty": "No recent runs.",
    "claw-runs-error": "Could not load run history. Please try again.",
    "claw-runs-download": "Download document again",
    "claw-runs-open-session": "Open session",
    "claw-runs-status-completed": "Completed",
    "claw-runs-status-waiting_approval": "Approval required",
    "claw-runs-status-failed": "Failed",
    "claw-runs-status-cancelled": "Cancelled",
    "claw-runs-next-waiting_approval": "This run is waiting for your decision; it has not completed.",
    "claw-runs-next-failed": "The run failed. A recorded file does not mean the task succeeded.",
    "claw-runs-next-cancelled": "This run was cancelled; no completion is claimed.",
    "claw-runs-kind-aria": "File type {kind}",
    "claw-runs-download-only": "This format is download-only. Save the file to view its contents.",
    "claw-approval-actions-aria": "Approval decision",
    "claw-approval-required": "This run is waiting for your approval.",
    "claw-approval-approve": "Approve",
    "claw-approval-deny": "Deny",
    "claw-approval-processing": "Processing your decision...",
    "claw-approval-error": "The approval decision could not be processed. Nothing was retried automatically.",
    "claw-approval-not-available": "This approval request is no longer available.",
  };


  // #7216 R5 A4 (claw-status): Claw status, pre-dispatch retry, and the
  // in-flight elapsed wait live in chat-claw-status-module.js. B7: the module
  // is on the registry (app.provide("clawStatus")) — all 19 one-line
  // forwarders are gone and callers reach the same methods through the
  // registry piece.
  function clawStatusModule() { return clawStatusModuleInstance; }

  // A generated document always retains its original bounded download action.
  // #3932 preview is separate and only appears for an actual PDF receipt,
  // with fresh server-side tenant validation and real PDF bytes.
  // #7216 R5 A5a (claw-run): Claw manual run artifacts, approval controls, and the
  // single execute entry point live in chat-claw-run-module.js. B7: the module
  // is on the registry (app.provide("clawRun")) — the one-line forwarders are
  // gone and callers reach the same methods through the registry piece.
  function clawRunModule() { return clawRun; }



  automationForm.wireEditListeners();


  automationForm.wireCreateListeners();


  automation.wireViewListeners();
  // #7173: the Chat | Claw | Util app switch reuses the two existing screen
  // entries so the Util screen never re-implements shell state. Kept next to
  // the functions it names (some Node harnesses evaluate a source slice).
  window.PadiemAppSwitch = Object.freeze({
    openChat: navModuleInstance.openChatWorkspace,
    openClaw: navModuleInstance.openClawWorkspace,
  });

  navModuleInstance.wireNavRouteListener();
  // #3222 Web Claw connector truth. The browser consumes the existing
  // read-only #2830 projection; it never becomes a connector/OAuth authority.
  // R5 part 2 B2: the connector declarations only this module uses (nav
  // button, dialog, loading, retry, the Drive/Gmail handoff constants and the
  // status/mount state) are owned by chat-connectors-module.js, whose module
  // is created here, at the original declaration position.
  const connectors = app.provide("connectors", window.PadiemChatConnectorsModule.create(Object.setPrototypeOf({

    get syncGoogleCalendarConnectButton() { return calendarModule().syncGoogleCalendarConnectButton; },
    get activateGoogleCalendarRead() { return calendarModule().activateGoogleCalendarRead; },
    get googleCalendarConnectButton() { return calendarModule().googleCalendarConnectButton; },
    get beginGoogleCalendarConnect() { return calendarModule().beginGoogleCalendarConnect; },
    get googleCalendarReadActivationAfterConnectReturn() { return googleCalendarReadActivationAfterConnectReturn; },
    set googleCalendarReadActivationAfterConnectReturn(value) { googleCalendarReadActivationAfterConnectReturn = value; },

  }, app)));
  let googleConnectorConnectInFlight = false;
  // In-session Calendar READ grant truth (#2952). "unknown" until this session
  // activates it; the status projection carries no persisted grant field, so
  // nothing here claims a grant the server has not just confirmed.
  let googleCalendarReadState = "unknown";
  // In-session Calendar READ grant truth (#2952). "unknown" until this session
  // activates it; the status projection carries no persisted grant field, so
  // nothing here claims a grant the server has not just confirmed.
  let googleCalendarReadActivationAfterConnectReturn = false;

  // #7216 R5 A9 (connectors): the connector surface — status cards, the
  // reviewed Google Drive / Gmail connect handoff and the standalone
  // Connectors page mount — lives in chat-connectors-module.js. app.js keeps
  // the declarations, the OAuth-return handling and a single wire call at the
  // original listener position. The module API is on the registry.
  function connectorsModule() { return connectors; }

  /** Projects the READ-grant axis onto the Calendar card's own state line.
   *  Only visible while the OAuth/workspace axis is "connected"; every value
   *  is one of the four closed session states, rendered through the bounded
   *  textContent sink. */


  connectorsModule().wireConnectorsListeners();

  const connectorReturnSearch = typeof window.location.search === "string" ? window.location.search : "";
  const connectorReturnParts = connectorReturnSearch.replace(/^\?/, "").split("&").filter(Boolean);
  const connectorReturned = connectorReturnParts.some((part) => part === "google_connector=connected");
  if (connectorReturned) {
    googleCalendarReadActivationAfterConnectReturn = true;
    const cleanQuery = connectorReturnParts.filter((part) => !part.startsWith("google_connector=")).join("&");
    const cleanPath = String(window.location.pathname || "/");
    const cleanHash = String(window.location.hash || "");
    window.history.replaceState(null, "", cleanPath + (cleanQuery ? `?${cleanQuery}` : "") + cleanHash);
    connectors.openConnectorsDialog();
  }

  if (connectorReturnParts.some(part => part === "claw-github=connected")) {
    const cleanQuery = connectorReturnParts.filter(part => !part.startsWith("claw-github=")).join("&");
    const cleanPath = String(window.location.pathname || "/");
    const cleanHash = String(window.location.hash || "");
    window.history.replaceState(null, "", cleanPath + (cleanQuery ? "?" + cleanQuery : "") + cleanHash);
    navModuleInstance.openClawWorkspace();
  }

  navModuleInstance.wireNavEntryListeners();
  // #4462: background task history stays reachable from the general Claw
  // entry bar (#3531 keeps the workspace canvas hidden in general/manual
  // views, so the entry lives beside the manual-entry control instead).
  // In-conversation run status/results are unchanged.
  clawForm.wireModeChips();
  navModuleInstance.setNavActive();


  clawForm.wireManualForm();

  // Keep preview/execute hints in sync with locale switches (data-locale-key auto-syncs static text,
  // but status and dynamic card chrome need manual refresh when language toggles).
  window.addEventListener("padiem:localechange", () => {
    // Wait state owns the status region while a long-wait stage is announced:
    // re-render its copy from state so the elapsed value is preserved rather
    // than reset by a language switch.
    if (clawWaitStartedAt && clawStatusModule().renderClawWait()) clawStatusModule().applyClawWaitStageCopy();
    else if (clawStatus && !clawStatus.hidden && clawStatus.dataset.localeKey) {
      clawStatus.textContent = coreModule().clawT(clawStatus.dataset.localeKey);
    }
    // Recovery copy carries runtime values, so it is re-rendered from state
    // instead of being re-resolved from a locale key.
    if (clawRetryBox && !clawRetryBox.hidden) clawStatusModule().renderClawRetryBox();
    if (clawRetryHint && !clawRetryHint.hidden && clawRetryHint.dataset.localeKey) {
      clawRetryHint.textContent = coreModule().clawT(clawRetryHint.dataset.localeKey);
    }
    // Re-apply badge text to current card state if visible
    if (clawResultCard && !clawResultCard.hidden && clawResultBadge) {
      const isExecuted = clawResultBadge.dataset.localeKey === "claw-result-badge-run";
      try { clawResultBadge.textContent = window.__padiemLocale.text(isExecuted ? "claw-result-badge-run" : "claw-result-badge"); } catch (_) {}
    }
  });

  coreModule().setNote(coreModule().idleNote());
  projectModule.renderProjectState();
  conversationModule().updateComposer();
  // A guide example arrives as text only: it fills the composer, sends nothing,
  // and leaves no query in the address bar for the next refresh to replay.
  const exampleOnLoad = examplePromptFromLocation();
  if (exampleOnLoad) {
    input.value = exampleOnLoad;
    conversationModule().updateComposer();
    try {
      window.history.replaceState(null, "", window.location.pathname);
    } catch (_) {}
  }
  window.PadiemChatSession.bind({
    clearHistoryUI: historyModule().clearHistoryUI, clearProjectsUI: projectModule.clearProjectsUI, resetConversationView: conversationModule().resetConversationView, clearAndroidHandoff: androidHandoffModule().clearAndroidHandoff,
    hasAndroidHandoff: () => Boolean(androidHandoff),
    clearHandoffStorage: () => {
      try { window.sessionStorage.removeItem(ANDROID_HANDOFF_STORAGE_KEY); } catch (_) {}
    },
  });
  window.PadiemClawSession.bind({
    noteApprovalSession: authModule().noteClawApprovalSession,
    clearRecovery: clawStatusModule().clearClawRecovery,
    clearWait: clawStatusModule().clearClawWait,
  });
  // #5481: a mailed one-time link opens the reset confirm view directly, so
  // the member lands on the "set a new password" step without signing in.
  const resetLinkOnLoad = accountModule().passwordResetTokenFromLocation();
  if (resetLinkOnLoad) {
    void authModule().loadAuthStatus().then(() => loginDialogModule().openAuthDialog());
  } else {
    void authModule().loadAuthStatus();
  }
  resumeAndroidHandoff();
  // Initial state
  clawStatusModule().setClawAreaState("idle");
  clawRun.clearClawArtifact();


  clawForm.wireExecuteControls();

  // R5 A2: the approved-memory module owns its declarations (rule (a)) and
  // wires its refresh listener here at the original position (rule (b)).
  const memory = app.provide("memory",
    window.PadiemChatMemoryModule.create(app));
  memory.wireMemoryListeners();

  // Claw recent-run presentation (#2317 owner-scoped run history route).
  // Presentation only: the browser renders what GET /api/claw/runs already
  // exposes to the signed-in owner and never mints its own run/history truth.
  // #4488 Phase A: recent runs are progressive disclosure on the Claw entry.

  let clawRunHistoryInFlight = false;
  // #3932: server caps owner-scoped history at MAX_CLAW_RUNS=30.
  // Expanding is a read-only, explicit user action, not pagination authority.
  let clawRunHistoryLimit = 10;
  let pendingClawRunFocusId = "";
  const clawRunHistoryPdfControllers = new Set();
  // R5 B7: the run-history module is on the registry (app.provide below); its
  // API is reached through the registry instead of app.js one-line forwarders.

  // R5 A2: the run-history module owns the runs-read cache, card renderer, and
  // filter/refresh/expand buttons (rule (a)), wired at the original position.
  const runHistory = app.provide("runHistory",
    window.PadiemChatRunHistoryModule.create(app));

  memory.wireMemoryReviewContract();
  runHistory.wireRunHistoryListeners();

  // R5 B1: the local PC panel owns its declarations (rule (a)) and registers
  // its listeners at this original position (rule (b)); the window contract
  // exposure keeps its original timing inside wire().
  const localPcPanel = app.provide("localPcPanel",
    window.PadiemChatLocalPcPanelModule.create(app));
  localPcPanel.wire();
  // Restore the Automation surface only after all handlers are registered.
  // It remains read-only for signed-out sessions through openClawAutomation().
  // #4862: restore Claw the same way. An unknown or tampered fragment matches
  // neither route, so the shell keeps its default Chat home.
  if (window.location.hash === AUTOMATION_ROUTE_HASH) app.openClawAutomation();
  else if (window.location.hash === CLAW_ROUTE_HASH) navModuleInstance.openClawWorkspace();
  else if (window.location.hash === CONNECTORS_ROUTE_HASH) connectors.openConnectorsView();
  else if (window.location.hash === ADVANCED_SETTINGS_ROUTE_HASH) settings.openAdvancedSettingsView();
  // Calendar, Library and Meeting are reachable only through the menu, so a
  // shared link used to land on Chat with whatever fragment the previous screen
  // left behind. Each of the three now names itself, and the screen that owns
  // the surface opens it: Calendar and Library answer the published request
  // from their own modules. #7365: Meeting has no sidebar entry any more — the
  // Util tab's meeting tool screen is the meeting home, so a stale bookmark of
  // the capture screen continues there (the capture trigger stays mounted in
  // that screen's body).
  const requestedRouteHash = String(window.location.hash || "");
  if (requestedRouteHash === CALENDAR_ROUTE_HASH
    || requestedRouteHash === LIBRARY_ROUTE_HASH
    || requestedRouteHash === MEETING_ROUTE_HASH) {
    const restoreShellRouteFromHash = () => {
      if (requestedRouteHash === MEETING_ROUTE_HASH) {
        window.location.hash = "#util/meeting";
        return;
      }
      window.dispatchEvent(new CustomEvent("padiem:route-restore", {
        detail: Object.freeze({ hash: requestedRouteHash }),
      }));
    };
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", restoreShellRouteFromHash, { once: true });
    } else {
      restoreShellRouteFromHash();
    }
    // The Library surface closes itself while the session is still unknown,
    // which lands after this restore has already opened it. Applying the named
    // screen again once the session is known gives a shared link the same
    // result as clicking that entry by hand after the page settles. The frame
    // delay matters: the module's own handler for this event runs first, so
    // the surface is restored after it has finished reacting to the session.
    window.addEventListener("padiem:auth-state", () => {
      window.requestAnimationFrame(restoreShellRouteFromHash);
    }, { once: true });
  }
  automationDestinationReady = true;
})();
