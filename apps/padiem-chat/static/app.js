(() => {
  "use strict";

  // R5 B1: the shared app context — the module registry (rule (d)) and the
  // namespace the pilot zones read shared state through (rule (c)). app.js
  // keeps owning authState/shell/clawWorkspace and the shared functions
  // until R5 B6; they are mounted here as live accessors.
  const app = window.PadiemChatAppContext.create({
    get authState() { return authState; },
    get shell() { return shell; },
    get clawWorkspace() { return clawWorkspace; },
    get emptyState() { return emptyState; },
    get uiT() { return uiT; },
    get clawT() { return clawT; },
    get setNavActive() { return setNavActive; },
    get closeSidebar() { return closeSidebar; },
    get clearClawWait() { return clearClawWait; },
    get syncClawRunHistoryVisibility() { return syncClawRunHistoryVisibility; },
    get mappedUiError() { return mappedUiError; },
    get approvedMemoryErrorMessage() { return approvedMemoryErrorMessage; },
    get safeLocalUiMessage() { return safeLocalUiMessage; },
    get failureCodeNote() { return failureCodeNote; },
    get openSavedConversation() { return openSavedConversation; },
    get downloadClawArtifact() { return downloadClawArtifact; },
    get setClawRunHistoryStatus() { return setClawRunHistoryStatus; },
    get clawRunHistoryPdfControllers() { return clawRunHistoryPdfControllers; },
    get renderClawApprovalControls() { return renderClawApprovalControls; },
    get loadClawRunHistory() { return loadClawRunHistory; },
    get clawRunHistoryInFlight() { return clawRunHistoryInFlight; },
    get clawRunHistoryLimit() { return clawRunHistoryLimit; },
    set clawRunHistoryLimit(value) { clawRunHistoryLimit = value; },
  });
  // #7216 R5 A7 (core): text lookup, note, error mapping, document readers,
  // formatters live in chat-core-module.js. app.js keeps one-line forwarders
  // and passes dependencies via getters.
  let coreModuleInstance = null;
  function coreModule() {
    if (!coreModuleInstance) {
      coreModuleInstance = window.PadiemChatCoreModule.create({
        get activeProject() { return activeProject; },
        get attachmentCopy() { return attachmentCopy; },
        get runtimeNote() { return runtimeNote; },
        get ALLOWED_DOCUMENT_TYPES() { return ALLOWED_DOCUMENT_TYPES; },
        get DOCUMENT_EXTENSION_TYPES() { return DOCUMENT_EXTENSION_TYPES; },
        get ALLOWED_IMAGE_TYPES() { return ALLOWED_IMAGE_TYPES; },
        get clawFallbackCopy() { return clawFallbackCopy; },
      });
    }
    return coreModuleInstance;
  }
  // #7216 R5 step 1: the settings/sidebar modules own those sections. app.js keeps
  // one-line forwarders with the same names, so call sites and function-declaration
  // hoisting stay intact. deps getters/setters read the closure variables live, so a
  // value changed before the first call is still observed.
  let settingsModuleInstance = null;
  let sidebarModuleInstance = null;
  function settingsModule() {
    if (!settingsModuleInstance) {
      settingsModuleInstance = window.PadiemChatSettingsModule.create({
        get settingsDialog() { return settingsDialog; },
        get settingsButton() { return settingsButton; },
        get profileToggle() { return profileToggle; },
        get advancedSettingsView() { return advancedSettingsView; },
        get advancedSettingsReturnState() { return advancedSettingsReturnState; },
        set advancedSettingsReturnState(value) { advancedSettingsReturnState = value; },
        get shell() { return shell; },
        get setNavActive() { return setNavActive; },
        get selectAdvancedMenu() { return selectAdvancedMenu; },
      });
    }
    return settingsModuleInstance;
  }
  function sidebarModule() {
    if (!sidebarModuleInstance) {
      sidebarModuleInstance = window.PadiemChatSidebarModule.create({
        get shell() { return shell; },
        get sidebarCollapseButton() { return sidebarCollapseButton; },
        get sidebarRestoreButton() { return sidebarRestoreButton; },
        get mobileMenu() { return mobileMenu; },
        get mobileClose() { return mobileClose; },
        get sidebarScrim() { return sidebarScrim; },
        get closeProfilePanel() { return closeProfilePanel; },
      });
    }
    return sidebarModuleInstance;
  }
  // #7216 R5 step 2: the calendar module owns the Google Calendar READ pair.
  let calendarModuleInstance = null;
  function calendarModule() {
    if (!calendarModuleInstance) {
      calendarModuleInstance = window.PadiemChatCalendarModule.create({
        get connectorsScope() { return connectorsScope; },
        get authState() { return authState; },
        get googleConnectorConnectInFlight() { return googleConnectorConnectInFlight; },
        set googleConnectorConnectInFlight(value) { googleConnectorConnectInFlight = value; },
        get googleCalendarReadState() { return googleCalendarReadState; },
        set googleCalendarReadState(value) { googleCalendarReadState = value; },
        get GOOGLE_CALENDAR_CONNECTOR() { return GOOGLE_CALENDAR_CONNECTOR; },
        get GOOGLE_CALENDAR_TICKET_ENDPOINT() { return GOOGLE_CALENDAR_TICKET_ENDPOINT; },
        get connectorTicketErrorKey() { return connectorTicketErrorKey; },
        get GOOGLE_CALENDAR_READ_ACTIVATION_ENDPOINT() { return GOOGLE_CALENDAR_READ_ACTIVATION_ENDPOINT; },
        get setConnectorCopy() { return setConnectorCopy; },
        get connectorsError() { return connectorsError; },
        get openAuthDialog() { return openAuthDialog; },
        get fetch() { return fetch; },
        get reviewedGoogleAuthorizationUrl() { return reviewedGoogleAuthorizationUrl; },
      });
    }
    return calendarModuleInstance;
  }
  function calendarReadStateKey(state) { return calendarModule().calendarReadStateKey(state); }
  function calendarReadActivationErrorKey(error) { return calendarModule().calendarReadActivationErrorKey(error); }
  function googleCalendarConnectButton() { return calendarModule().googleCalendarConnectButton(); }
  function googleCalendarCard() { return calendarModule().googleCalendarCard(); }
  function renderCalendarReadState() { return calendarModule().renderCalendarReadState(); }
  function syncGoogleCalendarConnectButton(row = null) { return calendarModule().syncGoogleCalendarConnectButton(row); }
  function beginGoogleCalendarConnect() { return calendarModule().beginGoogleCalendarConnect(); }
  function activateGoogleCalendarRead() { return calendarModule().activateGoogleCalendarRead(); }
  // #7216 R5 step 3: the recent-conversations-menu module owns the history
  // list (rename/pin/delete) and the Claw recent-run presentation. app.js keeps
  // one-line forwarders with the same names. deps getters/setters read the closure
  // variables live, so a value changed before the first call is still observed.
  let historyModuleInstance = null;
  function historyModule() {
    if (!historyModuleInstance) {
      historyModuleInstance = window.PadiemChatHistoryModule.create({
        get historySection() { return historySection; },
        get historyList() { return historyList; },
        get historyEmpty() { return historyEmpty; },
        get historyActionStatus() { return historyActionStatus; },
        get clawRunHistory() { return app.clawRunHistory; },
        get clawRunHistoryDisclosure() { return clawRunHistoryDisclosure; },
        get clawRunHistoryExpand() { return app.clawRunHistoryExpand; },
        get clawRunHistoryError() { return clawRunHistoryError; },
        get clawRunHistoryLoading() { return clawRunHistoryLoading; },
        get clawRunHistoryList() { return clawRunHistoryList; },
        get clawRunHistoryEmpty() { return clawRunHistoryEmpty; },
        get HISTORY_TITLE_MAX_CHARS() { return HISTORY_TITLE_MAX_CHARS; },
        get authState() { return authState; },
        get authViewEpoch() { return authViewEpoch; },
        get shell() { return shell; },
        get input() { return input; },
        get conversationState() { return conversationState; },
        get inFlight() { return inFlight; },
        get clawConversationIds() { return clawConversationIds; },
        get clawRunHistoryPdfControllers() { return clawRunHistoryPdfControllers; },
        get uiT() { return uiT; },
        get clawT() { return clawT; },
        get sidebarActionIcon() { return sidebarActionIcon; },
        get openSavedConversation() { return openSavedConversation; },
        get readClawRuns() { return app.readClawRuns; },
        get mappedUiError() { return mappedUiError; },
        get safeLocalUiMessage() { return safeLocalUiMessage; },
        get failureCodeNote() { return failureCodeNote; },
        get renderClawRunCard() { return app.renderClawRunCard; },
        get resetConversationView() { return resetConversationView; },
        get setNote() { return setNote; },
        get idleNote() { return idleNote; },
        get historyReadSequence() { return historyReadSequence; },
        set historyReadSequence(value) { historyReadSequence = value; },
        get clawConversationLabelsRead() { return clawConversationLabelsRead; },
        set clawConversationLabelsRead(value) { clawConversationLabelsRead = value; },
        get clawRunHistoryInFlight() { return clawRunHistoryInFlight; },
        set clawRunHistoryInFlight(value) { clawRunHistoryInFlight = value; },
        get clawRunHistoryLeftSurface() { return clawRunHistoryLeftSurface; },
        set clawRunHistoryLeftSurface(value) { clawRunHistoryLeftSurface = value; },
        get clawRunHistoryLimit() { return clawRunHistoryLimit; },
        set clawRunHistoryLimit(value) { clawRunHistoryLimit = value; },
        get clawRunHistoryVisibilityEpoch() { return clawRunHistoryVisibilityEpoch; },
        set clawRunHistoryVisibilityEpoch(value) { clawRunHistoryVisibilityEpoch = value; },
        get pendingClawRunFocusId() { return pendingClawRunFocusId; },
        set pendingClawRunFocusId(value) { pendingClawRunFocusId = value; },
      });
    }
    return historyModuleInstance;
  }
  // #7216 R5: the auth module owns those sections. app.js keeps one-line
  // forwarders with the same names. deps getters/setters read the closure
  // variables live, so a value changed before the first call is still observed.
  let authModuleInstance = null;
  function authModule() {
    if (!authModuleInstance) {
      authModuleInstance = window.PadiemChatAuthModule.create({
        get AUTH_SERVER_UNREACHABLE() { return AUTH_SERVER_UNREACHABLE; },
        get AUTH_UNREACHABLE_RETRY_DELAY_MS() { return AUTH_UNREACHABLE_RETRY_DELAY_MS; },
        get SESSION_PRESENTATION() { return SESSION_PRESENTATION; },
        get accountAvatar() { return accountAvatar; },
        get accountContainer() { return accountContainer; },
        get accountDeleteActions() { return accountDeleteActions; },
        get accountDeleteButton() { return accountDeleteButton; },
        get accountDeleteConfirm() { return accountDeleteConfirm; },
        get accountDeleteConfirmEmail() { return accountDeleteConfirmEmail; },
        get accountDeleteError() { return accountDeleteError; },
        get accountName() { return accountName; },
        get accountPasswordActions() { return accountPasswordActions; },
        get accountSettingsSection() { return accountSettingsSection; },
        get settingsAccountEmail() { return settingsAccountEmail; },
        get accountSharedDeleteButton() { return accountSharedDeleteButton; },
        get accountSharedDeleteConfirm() { return accountSharedDeleteConfirm; },
        get accountSharedDeleteConfirmEmail() { return accountSharedDeleteConfirmEmail; },
        get accountSharedDeleteError() { return accountSharedDeleteError; },
        get advancedAccountSection() { return advancedAccountSection; },
        get advancedSettingsView() { return advancedSettingsView; },
        get applyAuthState() { return applyAuthState; },
        get authDialog() { return authDialog; },
        get authDialogView() { return authDialogView; },
        set authDialogView(value) { authDialogView = value; },
        get authDivider() { return authDivider; },
        get authHandoff() { return authHandoff; },
        get authMethodEnabled() { return authMethodEnabled; },
        get authServerUnreachableError() { return authServerUnreachableError; },
        get authState() { return authState; },
        set authState(value) { authState = value; },
        get authViewEpoch() { return authViewEpoch; },
        set authViewEpoch(value) { authViewEpoch = value; },
        get clawApprovalEpoch() { return clawApprovalEpoch; },
        set clawApprovalEpoch(value) { clawApprovalEpoch = value; },
        get clawApprovalInFlight() { return clawApprovalInFlight; },
        set clawApprovalInFlight(value) { clawApprovalInFlight = value; },
        get clawApprovalSessionToken() { return clawApprovalSessionToken; },
        set clawApprovalSessionToken(value) { clawApprovalSessionToken = value; },
        get clearPasswordResetFragment() { return clearPasswordResetFragment; },
        get clearProjectsUI() { return clearProjectsUI; },
        get closeAuthDialog() { return closeAuthDialog; },
        get closePasswordChangeDialog() { return closePasswordChangeDialog; },
        get closeProfilePanel() { return closeProfilePanel; },
        get closeSettings() { return closeSettings; },
        get fetchAuthStatusOnce() { return fetchAuthStatusOnce; },
        get googleLoginButton() { return googleLoginButton; },
        get hidePasswordResetViews() { return hidePasswordResetViews; },
        get historyActionStatus() { return historyActionStatus; },
        get historyEmpty() { return historyEmpty; },
        get historyList() { return historyList; },
        get historySection() { return historySection; },
        get invalidateClawApprovalSession() { return invalidateClawApprovalSession; },
        get isAndroidWebView() { return isAndroidWebView; },
        get loadAuthStatus() { return loadAuthStatus; },
        get loadProjects() { return loadProjects; },
        get loadRecentConversations() { return loadRecentConversations; },
        get loginButton() { return loginButton; },
        get loveTreeHandoffFromLocation() { return loveTreeHandoffFromLocation; },
        get openAuthDialog() { return openAuthDialog; },
        get openClawRunTarget() { return openClawRunTarget; },
        get openSavedConversation() { return openSavedConversation; },
        get passwordAuthAnswer() { return passwordAuthAnswer; },
        get passwordAuthRequest() { return passwordAuthRequest; },
        get passwordChangeConfirm() { return passwordChangeConfirm; },
        get passwordChangeCurrent() { return passwordChangeCurrent; },
        get passwordChangeDialog() { return passwordChangeDialog; },
        get passwordChangeError() { return passwordChangeError; },
        get passwordChangeForm() { return passwordChangeForm; },
        get passwordChangeNew() { return passwordChangeNew; },
        get passwordChangeSubmit() { return passwordChangeSubmit; },
        get passwordLoginError() { return passwordLoginError; },
        get passwordLoginForm() { return passwordLoginForm; },
        get passwordLoginIdentifier() { return passwordLoginIdentifier; },
        get passwordLoginPassword() { return passwordLoginPassword; },
        get passwordLoginSubmit() { return passwordLoginSubmit; },
        get passwordRegisterEmail() { return passwordRegisterEmail; },
        get passwordRegisterError() { return passwordRegisterError; },
        get passwordRegisterForm() { return passwordRegisterForm; },
        get passwordRegisterName() { return passwordRegisterName; },
        get passwordRegisterPassword() { return passwordRegisterPassword; },
        get passwordRegisterSection() { return passwordRegisterSection; },
        get passwordRegisterSubmit() { return passwordRegisterSubmit; },
        get passwordResetConfirm() { return passwordResetConfirm; },
        get passwordResetConfirmError() { return passwordResetConfirmError; },
        get passwordResetConfirmForm() { return passwordResetConfirmForm; },
        get passwordResetConfirmStatus() { return passwordResetConfirmStatus; },
        get passwordResetConfirmSubmit() { return passwordResetConfirmSubmit; },
        get passwordResetConfirmView() { return passwordResetConfirmView; },
        get passwordResetEmail() { return passwordResetEmail; },
        get passwordResetNew() { return passwordResetNew; },
        get passwordResetOpen() { return passwordResetOpen; },
        get passwordResetPanel() { return passwordResetPanel; },
        get passwordResetRequestError() { return passwordResetRequestError; },
        get passwordResetRequestForm() { return passwordResetRequestForm; },
        get passwordResetRequestStatus() { return passwordResetRequestStatus; },
        get passwordResetRequestSubmit() { return passwordResetRequestSubmit; },
        get passwordResetRequestView() { return passwordResetRequestView; },
        get passwordResetToken() { return passwordResetToken; },
        set passwordResetToken(value) { passwordResetToken = value; },
        get passwordResetTokenFromLocation() { return passwordResetTokenFromLocation; },
        get pendingNotificationConversationId() { return pendingNotificationConversationId; },
        set pendingNotificationConversationId(value) { pendingNotificationConversationId = value; },
        get pendingNotificationRunId() { return pendingNotificationRunId; },
        set pendingNotificationRunId(value) { pendingNotificationRunId = value; },
        get profilePanel() { return profilePanel; },
        get profileToggle() { return profileToggle; },
        get projectsBadge() { return projectsBadge; },
        get renderAndroidHandoff() { return renderAndroidHandoff; },
        get resetAccountDeleteConfirm() { return resetAccountDeleteConfirm; },
        get resetAccountSharedDeleteConfirm() { return resetAccountSharedDeleteConfirm; },
        get resetConversationView() { return resetConversationView; },
        get resolveSessionPresentation() { return resolveSessionPresentation; },
        get scheduleSharedRefresh() { return scheduleSharedRefresh; },
        get setAuthFormError() { return setAuthFormError; },
        get setAuthStatusMessage() { return setAuthStatusMessage; },
        get setLoginButtonCopy() { return setLoginButtonCopy; },
        get setNavActive() { return setNavActive; },
        get setNote() { return setNote; },
        get shell() { return shell; },
        get showPasswordResetView() { return showPasswordResetView; },
        get startAndroidHandoff() { return startAndroidHandoff; },
        get syncApprovedMemoryVisibility() { return app.syncApprovedMemoryVisibility; },
        get syncAuthDialogMethods() { return syncAuthDialogMethods; },
        get syncClawRunHistoryVisibility() { return syncClawRunHistoryVisibility; },
        get syncDeleteButton() { return syncDeleteButton; },
        get uiT() { return uiT; },
      });
    }
    return authModuleInstance;
  }
  // #7216 R5: the conversation module owns those sections. app.js keeps one-line
  // forwarders with the same names. deps getters/setters read the closure
  // variables live, so a value changed before the first call is still observed.
  let conversationModuleInstance = null;
  function conversationModule() {
    if (!conversationModuleInstance) {
      conversationModuleInstance = window.PadiemChatConversationModule.create({
        get ALLOWED_IMAGE_TYPES() { return ALLOWED_IMAGE_TYPES; },
        get MESSAGE_LIFECYCLE() { return MESSAGE_LIFECYCLE; },
        get PRODUCT_CHAT() { return PRODUCT_CHAT; },
        get PRODUCT_CLAW() { return PRODUCT_CLAW; },
        get accountInitial() { return accountInitial; },
        get accountName() { return accountName; },
        get activeClawRunId() { return activeClawRunId; },
        set activeClawRunId(value) { activeClawRunId = value; },
        get activeProject() { return activeProject; },
        set activeProject(value) { activeProject = value; },
        get activeProjectFileCount() { return activeProjectFileCount; },
        set activeProjectFileCount(value) { activeProjectFileCount = value; },
        get activeRequestArticle() { return activeRequestArticle; },
        set activeRequestArticle(value) { activeRequestArticle = value; },
        get activeRequestCancelReason() { return activeRequestCancelReason; },
        set activeRequestCancelReason(value) { activeRequestCancelReason = value; },
        get activeRequestController() { return activeRequestController; },
        set activeRequestController(value) { activeRequestController = value; },
        get attachmentButton() { return attachmentButton; },
        get attachmentCapabilities() { return attachmentCapabilities; },
        get attachmentChipList() { return attachmentChipList; },
        get attachmentCopy() { return attachmentCopy; },
        get attachmentCountLimit() { return attachmentCountLimit; },
        get attachmentFileInput() { return attachmentFileInput; },
        get attachmentKeyCounter() { return attachmentKeyCounter; },
        set attachmentKeyCounter(value) { attachmentKeyCounter = value; },
        get attachmentTray() { return attachmentTray; },
        get attachmentTrayNote() { return attachmentTrayNote; },
        get binaryDocuments() { return binaryDocuments; },
        get buildRetryBox() { return buildRetryBox; },
        get cancelStreamButton() { return cancelStreamButton; },
        get clawArtifactShownFor() { return clawArtifactShownFor; },
        set clawArtifactShownFor(value) { clawArtifactShownFor = value; },
        get clawT() { return clawT; },
        get clearAttachment() { return clearAttachment; },
        get clearClawRecovery() { return clearClawRecovery; },
        get clearClawWait() { return clearClawWait; },
        get closeSidebar() { return closeSidebar; },
        get composerInlineHint() { return composerInlineHint; },
        get composerInlineHintTimer() { return composerInlineHintTimer; },
        set composerInlineHintTimer(value) { composerInlineHintTimer = value; },
        get conversationArtifactContext() { return conversationArtifactContext; },
        get conversationEpoch() { return conversationEpoch; },
        set conversationEpoch(value) { conversationEpoch = value; },
        get conversationProduct() { return conversationProduct; },
        get conversationState() { return conversationState; },
        get editProjectButton() { return editProjectButton; },
        get emptyState() { return emptyState; },
        get exitProject() { return exitProject; },
        get exitProjectButton() { return exitProjectButton; },
        get extensionOf() { return extensionOf; },
        get failureCodeNote() { return failureCodeNote; },
        get failureStatusLabel() { return failureStatusLabel; },
        get form() { return form; },
        get formatBytes() { return formatBytes; },
        get formatClockTime() { return formatClockTime; },
        get idleNote() { return idleNote; },
        get inFlight() { return inFlight; },
        set inFlight(value) { inFlight = value; },
        get input() { return input; },
        get lastCompletedAnswerRequest() { return lastCompletedAnswerRequest; },
        set lastCompletedAnswerRequest(value) { lastCompletedAnswerRequest = value; },
        get messageList() { return messageList; },
        get readDocumentFile() { return readDocumentFile; },
        get removeAttachmentItem() { return removeAttachmentItem; },
        get renderAttachmentChips() { return renderAttachmentChips; },
        get renderProjectState() { return renderProjectState; },
        get renderWebGroundingNotice() { return renderWebGroundingNotice; },
        get resetConversation() { return resetConversation; },
        get resetConversationView() { return resetConversationView; },
        get revealErrorState() { return revealErrorState; },
        get selectImage() { return selectImage; },
        get selectedAttachments() { return selectedAttachments; },
        set selectedAttachments(value) { selectedAttachments = value; },
        get sendButton() { return sendButton; },
        get setNavActive() { return setNavActive; },
        get setNote() { return setNote; },
        get shell() { return shell; },
        get switchConversationProduct() { return switchConversationProduct; },
        get uiT() { return uiT; },
        get updateComposer() { return updateComposer; },
      });
    }
    return conversationModuleInstance;
  }
  // #7216 R5 5b: the streaming section owns the async request lifetime.
  // app.js keeps one-line forwarders with the same names. deps
  // getters/setters read the closure variables live, so a value changed
  // before the first call is still observed.
  let streamingModuleInstance = null;
  function streamingModule() {
    if (!streamingModuleInstance) {
      streamingModuleInstance = window.PadiemChatStreamingModule.create({
        get MESSAGE_LIFECYCLE() { return MESSAGE_LIFECYCLE; },
        get activeClawRunId() { return activeClawRunId; },
        set activeClawRunId(value) { activeClawRunId = value; },
        get activeProject() { return activeProject; },
        set activeProject(value) { activeProject = value; },
        get activeRequestArticle() { return activeRequestArticle; },
        set activeRequestArticle(value) { activeRequestArticle = value; },
        get activeRequestCancelReason() { return activeRequestCancelReason; },
        set activeRequestCancelReason(value) { activeRequestCancelReason = value; },
        get activeRequestController() { return activeRequestController; },
        set activeRequestController(value) { activeRequestController = value; },
        get addAssistantShell() { return addAssistantShell; },
        get applyStreamDone() { return applyStreamDone; },
        get attachmentPayload() { return attachmentPayload; },
        get authState() { return authState; },
        get chatTransport() { return chatTransport; },
        get clawGeneralFailure() { return clawGeneralFailure; },
        get conversationEpoch() { return conversationEpoch; },
        get conversationProduct() { return conversationProduct; },
        get conversationState() { return conversationState; },
        get handleCustomRequestFailure() { return handleCustomRequestFailure; },
        get inFlight() { return inFlight; },
        set inFlight(value) { inFlight = value; },
        get input() { return input; },
        get invalidateClawRunsRead() { return app.invalidateClawRunsRead; },
        get lastCompletedAnswerRequest() { return lastCompletedAnswerRequest; },
        set lastCompletedAnswerRequest(value) { lastCompletedAnswerRequest = value; },
        get lifecycleForError() { return lifecycleForError; },
        get loadProjects() { return loadProjects; },
        get loadRecentConversations() { return loadRecentConversations; },
        get openAuthDialog() { return openAuthDialog; },
        get projectById() { return projectById; },
        get projectFileStatus() { return projectFileStatus; },
        get projectsReady() { return projectsReady; },
        get recoverStoredPcResult() { return recoverStoredPcResult; },
        get renderAnswer() { return renderAnswer; },
        get renderCancelled() { return renderCancelled; },
        get renderError() { return renderError; },
        get renderProjectState() { return renderProjectState; },
        get renderStreamError() { return renderStreamError; },
        get renderTyping() { return renderTyping; },
        get renderWebGroundingNotice() { return renderWebGroundingNotice; },
        get requestCompletedAnswer() { return requestCompletedAnswer; },
        get requestStreamingAnswer() { return requestStreamingAnswer; },
        get revealErrorState() { return revealErrorState; },
        get selectedProductTier() { return selectedProductTier; },
        get setNote() { return setNote; },
        get uiT() { return uiT; },
        get updateComposer() { return updateComposer; },
        get waitForAcceptedPcRun() { return waitForAcceptedPcRun; },
      });
    }
    return streamingModuleInstance;
  }
  // #7216 R5 A3 (pc-run): PC execution polling, unfinished-run resume, and
  // durable PC result recovery live in chat-pc-run-module.js. app.js keeps
  // one-line forwarders and reads closure state live via getters.
  let pcRunModuleInstance = null;
  function pcRunModule() {
    if (!pcRunModuleInstance) {
      pcRunModuleInstance = window.PadiemChatPcRunModule.create({
        get MESSAGE_LIFECYCLE() { return MESSAGE_LIFECYCLE; },
        get authState() { return authState; },
        get conversationProduct() { return conversationProduct; },
        get conversationState() { return conversationState; },
        get findUnfinishedPcRun() { return findUnfinishedPcRun; },
        get idleNote() { return idleNote; },
        get loadRecentConversations() { return loadRecentConversations; },
        get openSavedConversation() { return openSavedConversation; },
        get pcResultRecovery() { return pcResultRecovery; },
        get pcWaitElapsed() { return pcWaitElapsed; },
        get renderStoredPcAnswer() { return renderStoredPcAnswer; },
        get renderStreamError() { return renderStreamError; },
        get resolvedPcRuns() { return resolvedPcRuns; },
        get setNote() { return setNote; },
        get showPcRuntimeStatus() { return showPcRuntimeStatus; },
        get uiT() { return uiT; },
      });
    }
    return pcRunModuleInstance;
  }

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
  const mobileMenu = document.getElementById("mobileMenu");
  const mobileClose = document.getElementById("mobileClose");
  const sidebarCollapseButton = document.getElementById("sidebarCollapseButton");
  const sidebarRestoreButton = document.getElementById("sidebarRestoreButton");
  const sidebarScrim = document.getElementById("sidebarScrim");
  const settingsButton = document.getElementById("settingsButton");
  const settingsDialog = document.getElementById("settingsDialog");
  const settingsCloseButton = document.getElementById("settingsCloseButton");
  const accountSettingsSection = document.getElementById("accountSettingsSection");
  const settingsAccountEmail = document.getElementById("settingsAccountEmail");
  const advancedAccountSection = document.getElementById("advancedAccountSection");
  const accountPasswordActions = document.getElementById("accountPasswordActions");
  // #6659: account self-deletion. The server owns the authority and
  // the exact-email confirm; the browser only mirrors the same gate.
  const accountDeleteActions = document.getElementById("accountDeleteActions");
  const accountDeleteOpen = document.getElementById("accountDeleteOpen");
  const accountSharedDeleteOpen = document.getElementById("accountSharedDeleteOpen");
  const accountDeleteConfirm = document.getElementById("accountDeleteConfirm");
  const accountDeleteConfirmEmail = document.getElementById("accountDeleteConfirmEmail");
  const accountDeleteButton = document.getElementById("accountDeleteButton");
  const accountDeleteError = document.getElementById("accountDeleteError");
  const accountSharedDeleteConfirm = document.getElementById("accountSharedDeleteConfirm");
  const accountSharedDeleteConfirmEmail = document.getElementById("accountSharedDeleteConfirmEmail");
  const accountSharedDeleteButton = document.getElementById("accountSharedDeleteButton");
  const accountSharedDeleteError = document.getElementById("accountSharedDeleteError");
  const settingsLogoutButton = document.getElementById("settingsLogoutButton");
  const passwordChangeOpen = document.getElementById("passwordChangeOpen");
  const passwordChangeDialog = document.getElementById("passwordChangeDialog");
  const passwordChangeDialogClose = document.getElementById("passwordChangeDialogClose");
  const passwordChangeForm = document.getElementById("passwordChangeForm");
  const passwordChangeCurrent = document.getElementById("passwordChangeCurrent");
  const passwordChangeNew = document.getElementById("passwordChangeNew");
  const passwordChangeConfirm = document.getElementById("passwordChangeConfirm");
  const passwordChangeError = document.getElementById("passwordChangeError");
  const passwordChangeSubmit = document.getElementById("passwordChangeSubmit");
  const attachmentFileInput = document.getElementById("attachmentFileInput");
  const attachmentButton = document.getElementById("attachmentButton");
  const attachmentTray = document.getElementById("attachmentTray");
  const attachmentChipList = document.getElementById("attachmentChipList");
  const documentStarterButton = document.getElementById("documentStarterButton");
  const runtimeNote = document.getElementById("runtimeNote");
  const loginButton = document.getElementById("loginButton");
  const authDialog = document.getElementById("authDialog");
  const authDialogClose = document.getElementById("authDialogClose");
  const googleLoginButton = document.getElementById("googleLoginButton");
  const androidHandoffPanel = document.getElementById("androidHandoffPanel");
  const androidHandoffCode = document.getElementById("androidHandoffCode");
  const androidHandoffNote = document.getElementById("androidHandoffNote");
  const androidHandoffOpen = document.getElementById("androidHandoffOpen");
  const androidHandoffCopy = document.getElementById("androidHandoffCopy");
  const androidHandoffCopied = document.getElementById("androidHandoffCopied");
  const androidHandoffCancel = document.getElementById("androidHandoffCancel");
  const androidHandoffError = document.getElementById("androidHandoffError");
  const authDivider = document.getElementById("authDivider");
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
  const passwordResetRequestForm = document.getElementById("passwordResetRequestForm");
  const passwordResetEmail = document.getElementById("passwordResetEmail");
  const passwordResetRequestError = document.getElementById("passwordResetRequestError");
  const passwordResetRequestStatus = document.getElementById("passwordResetRequestStatus");
  const passwordResetRequestSubmit = document.getElementById("passwordResetRequestSubmit");
  const passwordResetConfirmForm = document.getElementById("passwordResetConfirmForm");
  const passwordResetNew = document.getElementById("passwordResetNew");
  const passwordResetConfirm = document.getElementById("passwordResetConfirm");
  const passwordResetConfirmError = document.getElementById("passwordResetConfirmError");
  const passwordResetConfirmStatus = document.getElementById("passwordResetConfirmStatus");
  const passwordResetConfirmSubmit = document.getElementById("passwordResetConfirmSubmit");
  const passwordResetBack = document.getElementById("passwordResetBack");
  const passwordResetConfirmBack = document.getElementById("passwordResetConfirmBack");
  let passwordResetToken = "";
  let authDialogView = "login";
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
  profileToggle.setAttribute("aria-label", uiT("account-profile-toggle"));
  // Some auth fixtures mount account controls without the original avatar as a
  // direct child; prepend never assumes a particular descendant relationship.
  accountContainer?.prepend(profileToggle);
  // Keep #accountAvatar and #accountName as direct accountContainer children:
  // product-capabilities.js rehomes fallback avatars before the account name.
  // A separate accessible button overlays those text/visual nodes instead.
  const profilePanel = document.createElement("div");
  profilePanel.id = "accountProfilePanel";
  profilePanel.className = "account-profile-panel";
  profilePanel.hidden = true;
  const profileSettingsAction = document.createElement("button");
  profileSettingsAction.type = "button";
  profileSettingsAction.className = "account-profile-settings";
  profileSettingsAction.dataset.localeKey = "account-profile-settings";
  profileSettingsAction.textContent = uiT("account-profile-settings");
  profilePanel.append(profileSettingsAction);
  accountContainer?.append(profilePanel);
  function closeProfilePanel(...a) { return authModule().closeProfilePanel(...a); }
  const historySection = document.getElementById("historySection");
  const historyList = document.getElementById("historyList");
  const historyActionStatus = document.getElementById("historyActionStatus");
  const historyEmpty = document.getElementById("historyEmpty");
  const projectsNavButton = document.getElementById("projectsNavButton");
  const projectsBadge = document.getElementById("projectsBadge");
  const projectsSection = document.getElementById("projectsSection");
  const projectsList = document.getElementById("projectsList");
  const projectsEmpty = document.getElementById("projectsEmpty");
  const projectCreateButton = document.getElementById("projectCreateButton");
  const projectBanner = document.getElementById("projectBanner");
  const activeProjectName = document.getElementById("activeProjectName");
  const activeProjectFiles = document.getElementById("activeProjectFiles");
  const editProjectButton = document.getElementById("editProjectButton");
  const exitProjectButton = document.getElementById("exitProjectButton");
  const projectDialog = document.getElementById("projectDialog");
  const projectForm = document.getElementById("projectForm");
  const projectDialogTitle = document.getElementById("projectDialogTitle");
  const projectDialogClose = document.getElementById("projectDialogClose");
  const projectDialogCancel = document.getElementById("projectDialogCancel");
  const projectNameInput = document.getElementById("projectNameInput");
  const projectInstructionsInput = document.getElementById("projectInstructionsInput");
  const projectFormError = document.getElementById("projectFormError");
  const projectSaveButton = document.getElementById("projectSaveButton");
  const projectFormActions = projectForm.querySelector(".project-form-actions");
  const projectDeleteButton = document.createElement("button");
  projectDeleteButton.id = "projectDeleteButton";
  projectDeleteButton.type = "button";
  projectDeleteButton.className = "project-danger";
  projectDeleteButton.textContent = uiT("project-delete");
  projectDeleteButton.hidden = true;
  projectDeleteButton.setAttribute("aria-label", uiT("project-delete-aria"));
  projectFormActions.prepend(projectDeleteButton);
  const projectFilesPanel = document.getElementById("projectFilesPanel");
  const projectFileInput = document.getElementById("projectFileInput");
  const projectFilesList = document.getElementById("projectFilesList");
  const projectFilesUsage = document.getElementById("projectFilesUsage");
  const projectFilesEmpty = document.getElementById("projectFilesEmpty");
  const projectFileStatus = document.getElementById("projectFileStatus");
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

  const PROJECT_BINARY_EXTENSION_MEDIA = new Map([
    [".pdf", "application/pdf"],
    [".hwpx", "application/hwp+zip"],
    [".docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"],
  ]);

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
  let attachmentKeyCounter = 0;
  let authState = { ready: false, authenticated: false, user: null, history_ready: false, project_files_ready: false };
  // UI read generations contain no account identifier. Every verified auth
  // refresh invalidates late sidebar responses from the previous session.
  let authViewEpoch = 0;
  let historyReadSequence = 0;
  // Only the owner-scoped Claw run history can identify a Claw thread.
  const clawConversationIds = new Set();
  let clawConversationLabelsRead = null;
  let projects = [];
  let projectsReady = false;
  // #5882: next-page cursor from the server. When present a "load more" button is
  // appended; on the last page there is none, so the list no longer stops silently at 50.
  let projectsNextCursor = null;
  let projectsLoadingMore = false;
  let activeProject = null;
  let activeProjectFileCount = 0;
  let editingProjectId = null;
  let dialogProjectFiles = [];

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

  function uiT(...a) { return coreModule().uiT(...a); }
  function attachmentCopy(...a) { return conversationModule().attachmentCopy(...a); }
  function idleNote(...a) { return coreModule().idleNote(...a); }
  function setNote(...a) { return coreModule().setNote(...a); }
  function hwpLegacyGuidance(...a) { return coreModule().hwpLegacyGuidance(...a); }
  // Short-lived overlay, not a new composer row.
  const composerInlineHint = document.getElementById("composerInlineHint");
  let composerInlineHintTimer = null;
  function showComposerInlineHint(...a) { return conversationModule().showComposerInlineHint(...a); }
  window.addEventListener("padiem:composer-hint", (event) => {
    if (event && event.detail && typeof event.detail.key === "string") {
      showComposerInlineHint(event.detail.key);
    }
  });
  sendButton.addEventListener("click", () => {
    // #5561: an empty composer shows the voice waveform, so the empty-message
    // notice belongs to the send arrow only.
    if (window.PadiemVoiceMenu?.isVoicePrimaryAction?.()) return;
    if (!input.value.trim() && !inFlight) showComposerInlineHint("composer-empty-message");
  });

  function updateComposer(...a) { return conversationModule().updateComposer(...a); }
  function lifecycleForError(error) {
    return error && error.code === "upstream_timeout" ? MESSAGE_LIFECYCLE.TIMED_OUT : MESSAGE_LIFECYCLE.FAILED;
  }
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
  const PANEL_ROUTE_HASH_BY_STATE = Object.freeze({
    calendar: CALENDAR_ROUTE_HASH,
    library: LIBRARY_ROUTE_HASH,
    meeting: MEETING_ROUTE_HASH,
    settings: ADVANCED_SETTINGS_ROUTE_HASH,
  });
  const OWNED_PANEL_HASHES = new Set(Object.values(PANEL_ROUTE_HASH_BY_STATE));
  let automationDestinationReady = false;
  // One page contract for every shell screen. This table is the only place a
  // screen names itself, says which dedicated panel it owns, lists the
  // sub-views that show the shared hero and marks its navigation entry; the
  // shell publishes `data-page-id` and `data-layout-variant` from it and the
  // shared stylesheet selects on those two attributes. A new page therefore
  // adds one entry here and reuses the Chat/Claw geometry instead of declaring
  // a second set of product rules. It moves existing conditions into data and
  // does not change which element is shown or hidden.
  const PAGE_VIEWS = Object.freeze([
    Object.freeze({ pageId: "home", navigationId: "newChatButton", layoutVariant: "conversation", panelId: null, heroViews: null }),
    Object.freeze({ pageId: "chat", navigationId: "newChatButton", layoutVariant: "conversation", panelId: null, heroViews: null }),
    Object.freeze({ pageId: "claw", navigationId: "clawNavButton", layoutVariant: "workspace", panelId: "clawWorkspace", heroViews: Object.freeze(["general"]) }),
    Object.freeze({ pageId: "connectors", navigationId: "connectorsNavButton", layoutVariant: "panel", panelId: null, heroViews: null }),
    Object.freeze({ pageId: "automation", navigationId: "automationNavButton", layoutVariant: "panel", panelId: null, heroViews: null }),
    Object.freeze({ pageId: "meeting", navigationId: "meetingNavButton", layoutVariant: "panel", panelId: "meetingView", heroViews: null }),
    Object.freeze({ pageId: "calendar", navigationId: "calendarNavButton", layoutVariant: "panel", panelId: null, heroViews: null }),
    Object.freeze({ pageId: "library", navigationId: "filesNavButton", layoutVariant: "panel", panelId: null, heroViews: null }),
    Object.freeze({ pageId: "settings", navigationId: "settingsButton", layoutVariant: "panel", panelId: null, heroViews: null }),
    Object.freeze({ pageId: "util", navigationId: "utilNavButton", layoutVariant: "panel", panelId: null, heroViews: null }),
  ]);
  const PAGE_VIEW_BY_ID = Object.freeze(
    PAGE_VIEWS.reduce((index, view) => Object.assign(index, { [view.pageId]: view }), {})
  );
  function pageViewFor(state) {
    return PAGE_VIEW_BY_ID[state] || PAGE_VIEW_BY_ID.home;
  }
  function syncRouteHash() {
    // 11-03 audit: every panel screen names itself in the URL. Calendar and
    // Library change the shell state from their own modules, so they ask for
    // this instead of repeating the fragment: the table below stays the only
    // place a screen names its own destination. A fragment this shell does not
    // own is left alone, exactly like the three routes above.
    if (!automationDestinationReady || !window.history || !window.location) return;
    const state = shell.dataset.state;
    const desired = PANEL_ROUTE_HASH_BY_STATE[state] || "";
    const currentHash = String(window.location.hash || "");
    if (currentHash === desired) return;
    const basePath = window.location.pathname + window.location.search;
    if (desired) {
      window.history.replaceState(window.history.state, "", basePath + desired);
    } else if (OWNED_PANEL_HASHES.has(currentHash)) {
      window.history.replaceState(window.history.state, "", basePath);
    }
  }
  window.PadiemChatRouting = Object.freeze({ syncRouteHash });
  function setNavActive() {
    const state = shell.dataset.state;
    const page = pageViewFor(state);
    // The URL fragment is the destination bookmark; no browser persistence.
    if (automationDestinationReady && window.history && window.location) {
      const currentHash = String(window.location.hash || "");
      const isAutomationRoute = currentHash === AUTOMATION_ROUTE_HASH;
      const isClawRoute = currentHash === CLAW_ROUTE_HASH;
      const isConnectorsRoute = currentHash === CONNECTORS_ROUTE_HASH;
      const basePath = window.location.pathname + window.location.search;
      if (state === "automation" && !isAutomationRoute) {
        window.history.replaceState(window.history.state, "", basePath + AUTOMATION_ROUTE_HASH);
      } else if (state === "claw" && !isClawRoute) {
        window.history.replaceState(window.history.state, "", basePath + CLAW_ROUTE_HASH);
      } else if (state === "connectors" && !isConnectorsRoute) {
        window.history.replaceState(window.history.state, "", basePath + CONNECTORS_ROUTE_HASH);
      } else if (state !== "automation" && isAutomationRoute) {
        window.history.replaceState(window.history.state, "", basePath);
      } else if (state !== "claw" && isClawRoute) {
        window.history.replaceState(window.history.state, "", basePath);
      } else if (state !== "connectors" && isConnectorsRoute) {
        window.history.replaceState(window.history.state, "", basePath);
      }
    }
    // The three panel screens above own their fragment through the same rule,
    // so this runs after them and only touches the fragments it names.
    syncRouteHash();
    const workspace = document.getElementById("clawWorkspace");
    const view = workspace ? String(workspace.dataset.view || "") : "";
    // The contract attribute the shared stylesheet selects on. Claw keeps one
    // conversation surface and changes only its working panel, so the hero
    // geometry follows the sub-views the entry lists instead of a product rule.
    const conversationHero = page.layoutVariant === "conversation" ||
      (Array.isArray(page.heroViews) && page.heroViews.includes(view));
    shell.dataset.pageId = page.pageId;
    shell.dataset.layoutVariant = conversationHero ? "conversation" : page.layoutVariant;
    PAGE_VIEWS.forEach((entry) => {
      if (!entry.panelId) return;
      const panel = document.getElementById(entry.panelId);
      if (panel) panel.hidden = entry.panelId !== page.panelId;
    });
    const modeBar = document.getElementById("clawManualForm");
    if (modeBar) modeBar.hidden = !(page.pageId === "claw" && view === "manual");
    // #3531: the explicit manual-entry control lives in the fixed composer
    // wrap and shows only on the general Claw view — never by default
    // elsewhere, never inside the manual form it opens.
    const entryBar = document.getElementById("clawManualEntryBar");
    if (entryBar) entryBar.hidden = !(page.pageId === "claw" && page.heroViews.includes(view));
    syncComposerForClaw(state === "claw");
    const chatNav = document.getElementById("newChatButton");
    const clawNav = document.getElementById("clawNavButton");
        // New Chat no longer shows a mode hint: the redundant label was removed
    // when the sidebar actions row was rearranged (B62 split-search task).
    if (clawNav) clawNav.dataset.modeHint = uiT("nav-claw-hint");
    // 11-03 audit: Calendar and Library own their menu row now, so the entry
    // stops claiming those two screens as well — otherwise two rows read as
    // current at once.
    if (chatNav) chatNav.setAttribute("aria-current", (state === "claw" || state === "connectors" || state === "automation" || state === "meeting" || state === "util") ? "false" : "page");
    if (chatNav && (state === "calendar" || state === "library")) chatNav.setAttribute("aria-current", "false");
    if (clawNav) clawNav.setAttribute("aria-current", state === "claw" ? "page" : "false");
    const utilNav = document.getElementById("utilNavButton");
    if (utilNav) utilNav.setAttribute("aria-current", state === "util" ? "page" : "false");
    const meetingNav = document.getElementById("meetingNavButton");
    if (meetingNav) meetingNav.setAttribute("aria-current", state === "meeting" ? "page" : "false");
    const connectorsNav = document.getElementById("connectorsNavButton");
    if (connectorsNav) connectorsNav.setAttribute("aria-current", state === "connectors" ? "page" : "false");
    const automationNav = document.getElementById("automationNavButton");
    if (automationNav) automationNav.setAttribute("aria-current", state === "automation" ? "page" : "false");
      }
  // #2505: Chat and Claw show the SAME conversation. Opening the other screen
  // changes the lane the next submit belongs to, and keeps the transcript, the
  // conversation id and the stored record exactly as they are — so a thread
  // started on one screen continues on the other.
  function switchConversationProduct(nextProduct) {
    const target = nextProduct === PRODUCT_CLAW ? PRODUCT_CLAW : PRODUCT_CHAT;
    if (conversationProduct === target) return;
    conversationState.setProduct?.(target);
    conversationProduct = target;
    const hasTurns = messageList.children.length > 0;
    messageList.hidden = !hasTurns;
    emptyState.hidden = hasTurns;
    // The Claw artifact index belongs to the Claw conversation only.
    if (target === PRODUCT_CLAW) {
      const clawConversationId = conversationState.getConversationId(PRODUCT_CLAW);
      if (clawConversationId && clawArtifactShownFor !== clawConversationId) {
        clawArtifactShownFor = clawConversationId;
        conversationArtifactContext?.show?.(clawConversationId);
      }
    } else {
      clawArtifactShownFor = "";
      conversationArtifactContext?.clear?.();
    }
  }
  // The first user turn extends the original landing panel. Older saved
  // threads still open directly on messages instead of replaying the hero.
  function showConversation(...a) { return conversationModule().showConversation(...a); }
  /* Owner 2026-10-20: the user avatar shows the first character of the
   * signed-in account name. The name -> avatar order is unchanged and the
   * initial is read from the live account display name, never hardcoded. */
  function accountInitial(...a) { return authModule().accountInitial(...a); }

  /* One clock format for both turns: the user turn and the answer row. */
  function formatClockTime(...a) { return coreModule().formatClockTime(...a); }

  function addUserMessage(...a) { return conversationModule().addUserMessage(...a); }
  // The runtime status chip has one owner (message-lifecycle.js). A finished
  // answer releases the "answer preparing" chip, and a real status (a Claw P01
  // stage, a failure) is never removed by accident. The calls go through the
  // global because a single-function harness evaluates this file's function in
  // a bare scope.
  function addAssistantShell(label, runtimeState) {
    const fragment = document.getElementById("assistantMessageTemplate").content.cloneNode(true);
    const article = fragment.querySelector(".assistant-message");
    // #3931: identify the product whose conversation is currently rendered.
    // The shared shell is not evidence that a Claw run came from Chat.
    const productLabel = article.querySelector("[data-assistant-product]");
    if (productLabel) productLabel.textContent = shell.dataset.state === "claw" ? "Padiem Claw" : "Padiem Chat";
    article.querySelector("[data-runtime-label]").textContent = label;
    window.PadiemChatLifecycle?.applyRuntimeLabel?.(article, label, runtimeState || "preparing");
    messageList.appendChild(fragment);
    PadiemChatLifecycle.set(article, MESSAGE_LIFECYCLE.STREAMING);
    return article;
  }
  function renderTyping(...a) { return historyModule().renderTyping(...a); }
  function renderStoredAssistant(text, stored) {
    const article = addAssistantShell(uiT("stored-conversation"), "status");
    // 11-03 audit: the chip named what it is without saying why it is there.
    // The hint rides the shared tooltip, so a hover, a keyboard focus and a
    // tap all read the same one line.
    const chip = article.querySelector("[data-runtime-label]");
    if (chip) {
      chip.dataset.localeTitle = "stored-conversation-hint";
      window.PadiemSharedTooltip?.label?.(chip, uiT("stored-conversation-hint"));
    }
    // A restored turn shows a time only when the store actually carries one.
    // Older records have no per-message time, and none is invented for them.
    const storedAt = stored && typeof stored.completed_at === "string" ? stored.completed_at : "";
    if (storedAt) article.dataset.completedAt = storedAt;
    const content = article.querySelector(".assistant-content");
    const paragraph = document.createElement("p");
    paragraph.textContent = text;
    content.appendChild(paragraph);
    PadiemChatLifecycle.set(article, MESSAGE_LIFECYCLE.COMPLETED);
  }
  function renderWebGroundingNotice(content, notice, metadata) {
    const code = metadata && metadata.web_grounding_error;
    const key = code === "web_grounding_no_evidence" ? "web-grounding-no-evidence-notice"
      : ["web_grounding_auth_error", "web_grounding_unavailable"].includes(code) ? "web-grounding-unavailable-notice" : null;
    if (!key || typeof notice !== "string") return;
    let note = content.querySelector(".web-grounding-notice");
    if (!note) {
      note = document.createElement("p");
      note.className = "web-grounding-notice reference-note";
      note.setAttribute("role", "status");
      content.prepend(note);
    }
    note.dataset.localeKey = key;
    note.textContent = uiT(key);
  }
  function renderAnswer(...a) { return conversationModule().renderAnswer(...a); }
  // #3936/#3933: a model HOLD is a bounded refusal raised BEFORE dispatch, so it
  // must not wear the generic "this run may already have started" state. Closed
  // code→copy map only: a raw server, Engine or provider string is never shown.
  const CLAW_BOUNDED_REFUSAL_COPY = Object.freeze({
    tier_unavailable: Object.freeze({
      message: "claw-general-model-unavailable",
      hint: "claw-general-model-unavailable-note",
    }),
    // Owner decision 2026-11-05: a guest Claw request is refused with 401
    // login_required; the UI names the login step instead of a generic error.
    login_required: Object.freeze({
      message: "claw-error-auth-needed",
      hint: "claw-login-required-note",
    }),
  });
  // Closed server code for a rejected customer-owned key. Named here so the
  // streaming answer region keeps no provider vocabulary of its own.
  const CUSTOM_AUTH_FAILURE_CODE = "custom_provider_auth_failed";
  // #3933: ONE lookup for every Claw failure surface. The composer lane, the live
  // SSE lane and the manual-intake lane all resolve the same server code through
  // this function, so a bounded refusal can never render two different sentences
  // or drift into a second invented copy. `Object.hasOwn` only: an inherited or
  // spoofed key never selects copy, and an unlisted code returns null so each
  // caller keeps its own existing fallback.
  function clawBoundedRefusalCopy(code) {
    const entry = typeof code === "string" && Object.hasOwn(CLAW_BOUNDED_REFUSAL_COPY, code)
      ? CLAW_BOUNDED_REFUSAL_COPY[code]
      : null;
    if (!entry) return null;
    return Object.freeze({ message: uiT(entry.message), hint: uiT(entry.hint) });
  }
  function clawGeneralFailure(code) {
    const bounded = clawBoundedRefusalCopy(code);
    if (bounded) return bounded;
    return Object.freeze({
      message: window.PadiemClawRecoveryTruth?.copy?.("unknown", document.documentElement.lang)
        || uiT("claw-general-check-runs"),
      hint: uiT("claw-general-check-runs"),
    });
  }
  function buildRetryBox(message, article, retryMessages, retrySkill, retryAttachment, retryContext, clawGeneralRequest = false, actionLabel = uiT("retry"), clawFailure = null) {
    const box = document.createElement("div");
    box.className = "error-box";
    const strong = document.createElement("strong");
    strong.textContent = uiT("answer-load-failed");
    const p = document.createElement("p");
    p.textContent = message || uiT("try-again");
    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = "retry-button";
    retry.textContent = actionLabel;
    // #3566: the general Claw P01 lane may already have dispatched before a
    // terminal Engine error. Do not offer a one-click replay (even manual)
    // until the operator checks existing results. Ordinary Chat retains its
    // established retry behavior; this guard is Claw-general only.
    if (clawGeneralRequest) {
      const hint = document.createElement("p");
      hint.textContent = uiT("claw-general-check-runs");
      // A provable pre-dispatch refusal has no run to check, so its next step is
      // a different model rather than the existing run-history guidance.
      if (clawFailure && clawFailure.hint) hint.textContent = clawFailure.hint;
      // #3935: navigation only. This button opens the existing owner-scoped
      // GET /api/claw/runs history and never replays the failed P01 POST.
      const openRuns = document.createElement("button");
      openRuns.type = "button";
      openRuns.className = "claw-inbox-retry claw-check-runs-button";
      openRuns.textContent = uiT("claw-general-open-runs");
      openRuns.disabled = authState.authenticated !== true;
      openRuns.addEventListener("click", () => {
        if (authState.authenticated !== true) return;
        openClawWorkspace(); // refresh is handled by existing owner-scoped history UI
        const history = document.getElementById("clawRunHistory");
        if (!history || history.hidden) return;
        // #4488 Phase A: the panel is progressive disclosure; open it so the
        // navigation target is actually visible and focusable.
        const historyDisclosure = document.getElementById("clawRunHistoryDisclosure");
        if (historyDisclosure) historyDisclosure.open = true;
        history.scrollIntoView?.({ block: "start", behavior: "smooth" });
        history.querySelector?.("#clawRunHistoryRefresh")?.focus?.();
      });
      box.append(strong, p, hint, openRuns);
      return box;
    }
    retry.addEventListener("click", async () => {
      article.remove();
      // #2505: the retry replays the request on the product that made it, with
      // the one shared conversation id.
      conversationState.setProduct?.(retryContext.product || conversationProduct);
      conversationState.setConversationId(retryContext.conversationId);
      activeProject = retryContext.project;
      renderProjectState();
      const success = await requestAnswer(retryMessages, retrySkill, retryAttachment, retryContext, clawGeneralRequest, true);
      if (success && selectedAttachments === retryAttachment) clearAttachment();
    }, { once: true });
    box.append(strong, p, retry);
    return box;
  }
  function revealErrorState(article) {
    article.scrollIntoView({ block: "center", behavior: "auto" });
  }
  // #5568: one bounded reason line under a Chat failure. Only the server's
  // compact code identifier is rendered; the message copy stays server/locale
  // authored. Claw keeps its existing refusal/recovery presentation, and an
  // unexpected string is never echoed into the notice.
  const FAILURE_CODE_PATTERN = /^[a-z][a-z0-9_]{0,63}$/;
  function failureCodeNote(errorCode, label) {
    if (typeof errorCode !== "string" || !FAILURE_CODE_PATTERN.test(errorCode)) return null;
    const note = document.createElement("small");
    note.className = "error-code";
    note.textContent = uiT("error-code-reference") + ": " + errorCode;
    return note;
  }
  function failureStatusLabel(lifecycle) {
    return lifecycle === MESSAGE_LIFECYCLE.TIMED_OUT ? uiT("timeout") : uiT("connection-error");
  }
  function renderError(article, message, retryMessages, retrySkill, retryAttachment, retryContext, clawGeneralRequest = false, lifecycle = MESSAGE_LIFECYCLE.FAILED, clawFailure = null, errorCode = "") {
    const content = article.querySelector(".assistant-content");
    content.replaceChildren();
    const statusLabel = failureStatusLabel(lifecycle);
    article.querySelector("[data-runtime-label]").textContent = statusLabel;
    // A failure is a real status: the chip stays visible with its own copy.
    window.PadiemChatLifecycle?.applyRuntimeLabel?.(article, statusLabel, "status");
    const box = buildRetryBox(message, article, retryMessages, retrySkill, retryAttachment, retryContext, clawGeneralRequest, undefined, clawFailure);
    const codeNote = clawGeneralRequest ? null : failureCodeNote(errorCode, statusLabel);
    if (codeNote) box.appendChild(codeNote);
    content.appendChild(box);
    PadiemChatLifecycle.set(article, lifecycle);
    revealErrorState(article);
  }
  function renderStreamError(...a) { return conversationModule().renderStreamError(...a); }
  function renderCancelled(article, retryMessages, retrySkill, retryContext, clawGeneralRequest = false) {
    const content = article.querySelector(".assistant-content");
    const typing = content.querySelector(".typing");
    if (typing) typing.remove();
    article.querySelector("[data-runtime-label]").textContent = uiT("generation-cancelled");
    window.PadiemChatLifecycle?.applyRuntimeLabel?.(article, uiT("generation-cancelled"), "status");
    content.appendChild(buildRetryBox(uiT("generation-cancelled-copy"), article, retryMessages, retrySkill, null, retryContext, clawGeneralRequest, uiT("regenerate")));
    PadiemChatLifecycle.set(article, MESSAGE_LIFECYCLE.CANCELLED);
    revealErrorState(article);
  }

  function formatBytes(...a) { return coreModule().formatBytes(...a); }
  function extensionOf(...a) { return coreModule().extensionOf(...a); }
  function documentMediaType(...a) { return coreModule().documentMediaType(...a); }
  function clearAttachment(...a) { return conversationModule().clearAttachment(...a); }
  function attachmentCountLimit(...a) { return conversationModule().attachmentCountLimit(...a); }
  function attachmentTrayNote(...a) { return conversationModule().attachmentTrayNote(...a); }
  function removeAttachmentItem(...a) { return conversationModule().removeAttachmentItem(...a); }
  function renderAttachmentChips(...a) { return conversationModule().renderAttachmentChips(...a); }
  function readAsText(...a) { return coreModule().readAsText(...a); }
  async function readDocumentFile(...a) { return coreModule().readDocumentFile(...a); }
  async function selectImage(...a) { return coreModule().selectImage(...a); }
  function addAttachmentFiles(...a) { return conversationModule().addAttachmentFiles(...a); }
  function attachmentPayload(...a) { return conversationModule().attachmentPayload(...a); }

  function clearHistoryUI(...a) { return historyModule().clearHistoryUI(...a); }
  // #4489: the Library entry is owned by static/library.js. The old
  // filesNavAvailable()/syncFilesNav() gate that also required project-file
  // storage was removed, because Library navigation must work for a signed-in
  // owner even when that storage is not provisioned.
  function clearProjectsUI() {
    projects = [];
    projectsReady = false;
    activeProject = null;
    activeProjectFileCount = 0;
    projectsList.replaceChildren();
    // #7365: the materials group (projects and recent conversations) stays
    // visible even with nothing in it — the section heading and the
    // empty-state note are the honest empty answer (a guest sees the same
    // group a signed-in account sees).
    projectsSection.hidden = false;
    projectsEmpty.hidden = false;
    setProjectsListNote("");
    if (projectsNavButton) {
      projectsNavButton.disabled = true;
      projectsNavButton.setAttribute("aria-disabled", "true");
    }
    if (projectsBadge) projectsBadge.textContent = authState.authenticated ? uiT("setup-needed") : uiT("login-after");
    renderProjectState();
  }
  function renderProjectState() {
    projectBanner.hidden = !activeProject;
    activeProjectName.textContent = activeProject ? activeProject.name : "";
    activeProjectFiles.hidden = !activeProject || activeProjectFileCount < 1;
    activeProjectFiles.textContent = activeProjectFileCount > 0 ? uiT("project-files-count", { count: activeProjectFileCount }) : "";
    projectsList.querySelectorAll(".project-item").forEach((button) => {
      button.setAttribute("aria-current", activeProject && button.dataset.projectId === activeProject.id ? "true" : "false");
    });
    if (!selectedAttachments.length) setNote(idleNote());
  }
  // Static, accessible sidebar actions: keep the translated button text
  // and ARIA labels; only replace the low-contrast visual affordance.
  function sidebarActionIcon(...a) { return sidebarModule().sidebarActionIcon(...a); }
  function renderProjects() {
    projectsList.replaceChildren();
    projectsSection.hidden = !projectsReady;
    projectsEmpty.hidden = !projectsReady || projects.length !== 0;
    projects.forEach((project) => {
      const row = document.createElement("div");
      row.className = "project-row";
      const button = document.createElement("button");
      button.type = "button";
      button.className = "recent-item project-item";
      button.dataset.projectId = project.id;
      button.textContent = project.name;
      button.setAttribute("aria-current", activeProject && activeProject.id === project.id ? "true" : "false");
      button.addEventListener("click", () => selectProject(project));
      const manage = document.createElement("button");
      manage.type = "button";
      manage.className = "project-manage";
      manage.textContent = uiT("manage");
      manage.prepend(sidebarActionIcon("settings"));
      manage.setAttribute("aria-label", uiT("project-manage-aria", { name: project.name }));
      window.PadiemSharedTooltip?.label?.(manage, uiT("project-manage-aria", { name: project.name }));
      manage.addEventListener("click", () => openProjectDialog(project));
      row.append(button, manage);
      projectsList.appendChild(row);
    });
    if (projectsNextCursor && projectsReady) {
      const moreRow = document.createElement("div");
      moreRow.className = "project-row project-more-row";
      const more = document.createElement("button");
      more.type = "button";
      more.className = "recent-item project-more";
      more.id = "projectsMore";
      more.textContent = uiT("projects-more");
      more.setAttribute("aria-label", uiT("projects-more-aria"));
      more.disabled = projectsLoadingMore;
      more.addEventListener("click", () => { void loadMoreProjects(); });
      moreRow.appendChild(more);
      projectsList.appendChild(moreRow);
    }
    if (projectsBadge) projectsBadge.textContent = projects.length ? String(projects.length) : uiT("create-new");
  }
  // #6645: a stale cursor used to report through the composer note, which the
  // glass desktop frame hides (display: none). The notice belongs next to the
  // list it is about, so it is always painted.
  function setProjectsListNote(text) {
    const note = document.getElementById("projectsListNote");
    if (!note) return;
    const copy = typeof text === "string" ? text : "";
    note.textContent = copy;
    note.hidden = !copy;
  }
  async function loadMoreProjects() {
    if (!projectsNextCursor || projectsLoadingMore || !authState.authenticated) return false;
    const epoch = authViewEpoch;
    const cursor = projectsNextCursor;
    projectsLoadingMore = true;
    renderProjects();
    try {
      const response = await fetch(
        `/api/projects?cursor=${encodeURIComponent(cursor)}`,
        { headers: { "Accept": "application/json" }, cache: "no-store" },
      );
      const data = await response.json().catch(() => null);
      if (epoch !== authViewEpoch || !authState.authenticated || !response.ok || !data || !Array.isArray(data.projects)) {
        // A cursor this server no longer accepts is answered 400. Refuse to loop:
        // drop it and show what is already on screen with a plain Korean notice.
        if (response.status === 400) {
          projectsNextCursor = null;
          setProjectsListNote(uiT("projects-more-stale"));
        }
        return false;
      }
      const seen = new Set(projects.map((item) => item.id));
      const fresh = data.projects.filter((item) => item && typeof item.id === "string"
        && typeof item.name === "string" && !seen.has(item.id));
      projects = projects.concat(fresh);
      projectsNextCursor = typeof data.next_cursor === "string" && data.next_cursor ? data.next_cursor : null;
      setProjectsListNote("");
      return true;
    } catch (_) {
      return false;
    } finally {
      projectsLoadingMore = false;
      if (epoch === authViewEpoch) renderProjects();
    }
  }
  async function loadProjects() {
    if (!authState.authenticated || !authState.history_ready) {
      clearProjectsUI();
      return false;
    }
    const epoch = authViewEpoch;
    if (projectsNavButton) {
      projectsNavButton.disabled = true;
      projectsNavButton.setAttribute("aria-disabled", "true");
    }
    if (projectsBadge) projectsBadge.textContent = uiT("checking");
    try {
      const response = await fetch("/api/projects", { headers: { "Accept": "application/json" }, cache: "no-store" });
      const data = await response.json().catch(() => null);
      if (epoch !== authViewEpoch || !authState.authenticated) return false;
      if (!response.ok || !data || !Array.isArray(data.projects)) throw new Error("projects unavailable");
      projects = data.projects.filter((item) => item && typeof item.id === "string" && typeof item.name === "string");
      projectsNextCursor = typeof data.next_cursor === "string" && data.next_cursor ? data.next_cursor : null;
      projectsReady = true;
      if (projectsNavButton) {
        projectsNavButton.disabled = false;
        projectsNavButton.setAttribute("aria-disabled", "false");
      }
      if (activeProject) activeProject = projects.find((item) => item.id === activeProject.id) || activeProject;
      renderProjects();
      return true;
    } catch (_) {
      if (epoch !== authViewEpoch || !authState.authenticated) return false;
      clearProjectsUI();
      return false;
    }
  }
  function projectById(id) {
    return projects.find((project) => project.id === id) || null;
  }
  async function ensureProject(id) {
    if (!id) return null;
    const known = projectById(id);
    if (known) return known;
    if (!authState.authenticated || !projectsReady) return null;
    const requestAuth = authState;
    try {
      const response = await fetch(`/api/projects/${encodeURIComponent(id)}`, { headers: { "Accept": "application/json" }, cache: "no-store" });
      const data = await response.json().catch(() => null);
      if (authState !== requestAuth || !authState.authenticated || !response.ok || !data || !data.project || typeof data.project.id !== "string") return null;
      projects.unshift(data.project);
      renderProjects();
      return data.project;
    } catch (_) {
      return null;
    }
  }

  // Only messages constructed by our own mapping may be shown to the user.
  function mappedUiError(...a) { return coreModule().mappedUiError(...a); }
  function safeLocalUiMessage(...a) { return conversationModule().safeLocalUiMessage(...a); }
  function showProjectError(error, fallback) {
    projectFormError.textContent = safeLocalUiMessage(error, fallback);
    const note = failureCodeNote(error?.code, "");
    if (note) projectFormError.appendChild(note);
    projectFormError.hidden = false;
  }

  async function fetchProjectFiles(projectId) {
    if (!authState.authenticated || !authState.project_files_ready || !projectId) return [];
    const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}/files`, { headers: { "Accept": "application/json" }, cache: "no-store" });
    const data = await response.json().catch(() => null);
    if (!response.ok || !data || !Array.isArray(data.files)) throw mappedUiError(uiT("project-files-load-failed"), data);
    return data.files.filter((item) => item && typeof item.id === "string" && typeof item.name === "string");
  }
  async function refreshActiveProjectFileCount() {
    if (!activeProject || !authState.project_files_ready) {
      activeProjectFileCount = 0;
      renderProjectState();
      return;
    }
    try {
      const files = await fetchProjectFiles(activeProject.id);
      activeProjectFileCount = files.length;
    } catch (_) {
      activeProjectFileCount = 0;
    }
    renderProjectState();
  }
  let highlightedProjectFileId = null;
  function renderProjectFiles() {
    projectFilesList.replaceChildren();
    const totalChars = dialogProjectFiles.reduce((sum, file) => sum + Number(file.content_chars || 0), 0);
    if (projectFilesUsage) {
      projectFilesUsage.textContent = uiT("project-files-usage", {
        count: dialogProjectFiles.length,
        chars: totalChars.toLocaleString(),
      });
      projectFilesUsage.hidden = false;
    }
    projectFilesEmpty.hidden = dialogProjectFiles.length !== 0;
    dialogProjectFiles.forEach((file) => {
      const row = document.createElement("div");
      row.className = "project-file-row";
      if (file.id === highlightedProjectFileId) {
        row.classList.add("quick-selected-file");
        row.tabIndex = -1;
        requestAnimationFrame(() => {
          if (projectDialog.open && editingProjectId && row.isConnected) {
            row.scrollIntoView({ block: "nearest" });
            row.focus({ preventScroll: true });
          }
        });
      }
      const copy = document.createElement("div");
      const strong = document.createElement("strong");
      strong.textContent = file.name;
      const small = document.createElement("small");
      small.textContent = `${file.media_type} · ${uiT("character-count", { count: Number(file.content_chars || 0).toLocaleString() })}`;
      copy.append(strong, small);
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = uiT("delete");
      remove.addEventListener("click", () => deleteProjectFile(file.id, file.name));
      row.append(copy, remove);
      projectFilesList.appendChild(row);
    });
  }
  async function loadProjectFilesForDialog(projectId) {
    if (!projectId || !authState.project_files_ready) {
      dialogProjectFiles = [];
      renderProjectFiles();
      return;
    }
    try {
      const files = await fetchProjectFiles(projectId);
      if (!projectDialog.open || editingProjectId !== projectId) return;
      dialogProjectFiles = files;
      renderProjectFiles();
      if (activeProject && activeProject.id === projectId) {
        activeProjectFileCount = dialogProjectFiles.length;
        renderProjectState();
      }
    } catch (error) {
      showProjectError(error, uiT("project-files-load-failed"));
    }
  }
  function projectBinaryMediaType(file) {
    // Project-scoped subset preflight: PDF/DOCX only (the server allow-lists exactly these two
    // binaries). Extension-driven to mirror document-binary.js canRead/canonicalMediaType, which
    // are themselves extension-canonical. Everything else — PPTX/XLSX and unsupported text types —
    // falls through to the text path and is rejected there BEFORE any request is made.
    return PROJECT_BINARY_EXTENSION_MEDIA.get(extensionOf(file && file.name)) || null;
  }
  let projectFileBusy = false;
  function setProjectFileBusy(busy) {
    projectFileBusy = busy;
    if (busy) {
      projectFilesPanel.setAttribute("aria-busy", "true");
      projectFileInput.setAttribute("aria-disabled", "true");
      if (projectFileStatus) { projectFileStatus.textContent = uiT("document-saving"); projectFileStatus.hidden = false; }
    } else {
      projectFilesPanel.removeAttribute("aria-busy");
      projectFileInput.removeAttribute("aria-disabled");
      if (projectFileStatus) { projectFileStatus.hidden = true; projectFileStatus.textContent = ""; }
    }
  }
  async function addProjectFile(file) {
    if (!file || !editingProjectId || !authState.project_files_ready) return;
    projectFileInput.value = "";
    if (projectFileBusy) return;
    // Clear any stale error so a successful retry never leaves the old message up.
    projectFormError.hidden = true;
    projectFormError.textContent = "";
    // #6126: a project .hwp is judged by its own bytes. The older OLE2 binary
    // Hangul format is never converted — the panel answers with the ordinary
    // save-as-HWPX guidance as a status note (not the error row) — and a
    // mislabeled file whose bytes are a real HWPX (ZIP) package keeps working
    // as HWPX through the same binary upload the .hwpx extension uses.
    const hwpFamily = extensionOf(file.name) === ".hwp"
      ? (await binaryDocuments?.headerFamily?.(file)) || null
      : null;
    if (hwpFamily === "ole") {
      if (projectFileStatus) {
        projectFileStatus.textContent = hwpLegacyGuidance();
        projectFileStatus.hidden = false;
      }
      return;
    }
    setProjectFileBusy(true);
    try {
      let projectBinary = projectBinaryMediaType(file);
      if (!projectBinary && hwpFamily === "zip" && binaryDocuments?.hwpxMedia) {
        projectBinary = binaryDocuments.hwpxMedia;
      }
      if (projectBinary) {
        // #6579: every binary goes through the shared tus module, which owns the
        // progress line, the resume policy and the first-party guidance copy.
        if (!window.PadiemProjectFileUpload) throw mappedUiError(uiT("project-file-save-failed"), null);
        const uploaded = await window.PadiemProjectFileUpload.upload({
          file,
          projectId: editingProjectId,
          mediaType: projectBinary,
          onProgress: (sent, total) => {
            if (projectFileStatus && !projectFileStatus.hidden && total > 0) {
              const percent = Math.min(100, Math.round((sent / total) * 100));
              projectFileStatus.textContent = `${uiT("document-saving")} ${percent}%`;
            }
          },
        });
        if (!uploaded || !uploaded.file) throw mappedUiError(uiT("project-file-save-failed"), null);
      } else {
        const documentFile = await readDocumentFile(file);
        const payload = { name: documentFile.name, media_type: documentFile.mediaType, text: documentFile.text };
        const response = await fetch(`/api/projects/${encodeURIComponent(editingProjectId)}/files`, {
          method: "POST", headers: { "Content-Type": "application/json", "Accept": "application/json" },
          body: JSON.stringify(payload),
        });
        const data = await response.json().catch(() => null);
        if (!response.ok || !data || !data.file) {
          throw mappedUiError(uiT("project-file-save-failed"), data);
        }
      }
      await loadProjectFilesForDialog(editingProjectId);
    } catch (error) {
      showProjectError(error, uiT("project-file-save-failed"));
    } finally {
      setProjectFileBusy(false);
    }
  }
  async function deleteProjectFile(fileId, name) {
    if (!editingProjectId || !authState.project_files_ready) return;
    const confirmed = await window.PadiemConfirmDialog.confirm({
      title: uiT("project-file-delete-title"),
      message: uiT("project-file-delete-message", { name }),
      cancelLabel: uiT("cancel"),
      confirmLabel: uiT("delete"),
    });
    if (!confirmed) return;
    try {
      const response = await fetch(`/api/projects/${encodeURIComponent(editingProjectId)}/files/${encodeURIComponent(fileId)}`, { method: "DELETE" });
      if (!response.ok) throw mappedUiError(uiT("project-file-delete-failed"), await response.json().catch(() => null));
      await loadProjectFilesForDialog(editingProjectId);
    } catch (error) {
      showProjectError(error, uiT("project-file-delete-failed"));
    }
  }

  function resetConversationView(...a) { return conversationModule().resetConversationView(...a); }
  // #2505: the sidebar Chat entry returns to the Chat lane while the user is in
  // the Claw workspace. Inside the Chat state the same entry starts a new
  // conversation. Every other caller resets the view directly, because a
  // sign-out, a project change or a delete must clear the conversation no
  // matter which product is on screen.
  function resetConversation(...a) { return conversationModule().resetConversation(...a); }
  function selectProject(project) {
    if (!projectsReady || !project || inFlight) return;
    activeProject = project;
    activeProjectFileCount = 0;
    resetConversationView(true);
    refreshActiveProjectFileCount();
  }
  function exitProject() {
    if (inFlight) return;
    activeProject = null;
    activeProjectFileCount = 0;
    resetConversationView(false);
  }
  function openProjectDialog(project = null, selectedFileId = null) {
    if (!projectsReady || !authState.authenticated || inFlight) return;
    editingProjectId = project ? project.id : null;
    highlightedProjectFileId = selectedFileId;
    projectDialogTitle.textContent = project ? uiT("project-edit-title") : uiT("project-new");
    projectNameInput.value = project ? project.name : "";
    projectInstructionsInput.value = project && typeof project.instructions === "string" ? project.instructions : "";
    projectFormError.textContent = "";
    projectFormError.hidden = true;
    projectSaveButton.disabled = false;
    projectDeleteButton.hidden = !project;
    projectDeleteButton.disabled = false;
    projectFilesPanel.hidden = !(project && authState.project_files_ready);
    dialogProjectFiles = [];
    renderProjectFiles();
    projectDialog.showModal();
  // #3190: an existing project loads its Drive case-folder status; a brand new
  // project has no project_id yet, so the Drive section stays hidden.
  const drivePanel = document.getElementById("projectDrivePanel");
  if (window.padiemProjectDriveFolder) {
    window.padiemProjectDriveFolder.reset();
    if (project && project.id) {
      if (drivePanel) drivePanel.hidden = false;
      window.padiemProjectDriveFolder.loadStatus(project.id);
    } else if (drivePanel) {
      drivePanel.hidden = true;
    }
  }
    if (project && authState.project_files_ready) loadProjectFilesForDialog(project.id);
    projectNameInput.focus();
  }
  function closeProjectDialog() {
    if (window.padiemProjectDriveFolder) window.padiemProjectDriveFolder.reset();
  if (projectDialog.open && typeof projectDialog.close === "function") projectDialog.close();
    editingProjectId = null;
    dialogProjectFiles = [];
    projectFileInput.value = "";
    projectFormError.textContent = "";
    projectFormError.hidden = true;
  }
  async function saveProject(event) {
    event.preventDefault();
    if (!projectsReady || !authState.authenticated) return;
    const name = projectNameInput.value.trim();
    const instructions = projectInstructionsInput.value.trim();
    if (!name) {
      projectFormError.textContent = uiT("project-name-required");
      projectFormError.hidden = false;
      return;
    }
    projectSaveButton.disabled = true;
    projectFormError.hidden = true;
    try {
      const editing = Boolean(editingProjectId);
      const url = editing ? `/api/projects/${encodeURIComponent(editingProjectId)}` : "/api/projects";
      const response = await fetch(url, {
        method: editing ? "PATCH" : "POST",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        body: JSON.stringify({ name, instructions }),
      });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || !data.project) {
        throw mappedUiError(uiT("project-save-failed"), data);
      }
      const saved = data.project;
      const index = projects.findIndex((item) => item.id === saved.id);
      if (index >= 0) projects[index] = saved; else projects.unshift(saved);
      if (activeProject && activeProject.id === saved.id) activeProject = saved;
      renderProjects();
      renderProjectState();
      closeProjectDialog();
      if (!editing) selectProject(saved);
    } catch (error) {
      showProjectError(error, uiT("project-save-failed"));
      projectSaveButton.disabled = false;
    }
  }

  async function deleteProject() {
    if (!editingProjectId || !projectsReady || !authState.authenticated || inFlight) return;
    const project = projectById(editingProjectId);
    if (!project) return;
    const confirmed = await window.PadiemConfirmDialog.confirm({
      title: uiT("project-delete-title"),
      message: uiT("project-delete-message", { name: project.name }),
      cancelLabel: uiT("cancel"),
      confirmLabel: uiT("delete"),
    });
    if (!confirmed) return;
    const deletingId = editingProjectId;
    const deletingActiveProject = Boolean(activeProject && activeProject.id === deletingId);
    projectDeleteButton.disabled = true;
    projectSaveButton.disabled = true;
    projectFormError.hidden = true;
    try {
      const response = await fetch(`/api/projects/${encodeURIComponent(deletingId)}`, {
        method: "DELETE",
        headers: { "Accept": "application/json" },
        cache: "no-store",
      });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || data.deleted !== true || data.project_id !== deletingId) {
        throw mappedUiError(uiT("project-delete-failed"), data);
      }
      projects = projects.filter((item) => item.id !== deletingId);
      if (deletingActiveProject) {
        activeProject = null;
        activeProjectFileCount = 0;
      }
      renderProjects();
      renderProjectState();
      closeProjectDialog();
      await loadProjects();
      if (deletingActiveProject) {
        renderProjectState();
        setNote(idleNote());
      }
      input.focus();
    } catch (error) {
      showProjectError(error, uiT("project-delete-failed"));
      projectDeleteButton.disabled = false;
      projectSaveButton.disabled = false;
    }
  }

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
  const SESSION_PRESENTATION = {
    "pending": { "accountHidden": true, "loginHidden": true, "loginDisabled": true, "accountNameHidden": true },
    "signed_in": { "accountHidden": false, "loginHidden": true, "loginDisabled": false, "accountNameHidden": false },
    "guest": { "accountHidden": false, "loginHidden": false, "loginDisabled": false, "accountNameHidden": false },
    "expired": { "accountHidden": false, "loginHidden": false, "loginDisabled": false, "accountNameHidden": false },
    "unavailable": { "accountHidden": true, "loginHidden": true, "loginDisabled": true, "accountNameHidden": true },
    "unreachable": { "accountHidden": false, "loginHidden": false, "loginDisabled": false, "accountNameHidden": true }
  };
  function resolveSessionPresentation(...a) { return authModule().resolveSessionPresentation(...a); }
  // The other projections read the same rule so they cannot drift apart.
  window.PadiemSessionPresentation = resolveSessionPresentation;

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

  function setLoginButtonCopy(...a) { return authModule().setLoginButtonCopy(...a); }
  function applyAuthState(...a) { return authModule().applyAuthState(...a); }
  function authMethodEnabled(...a) { return authModule().authMethodEnabled(...a); }

  function setAuthFormError(...a) { return authModule().setAuthFormError(...a); }


  // #7216 R5 A6 (android-handoff): start/claim/poll and the handoff panel live
  // in chat-android-handoff-module.js. app.js keeps the declarations, the
  // session-storage reader/writer and resumeAndroidHandoff (R-06), plus one-line
  // forwarders so existing call sites and deps stay intact.
  let androidHandoffModuleInstance = null;
  function androidHandoffModule() {
    if (!androidHandoffModuleInstance) {
      androidHandoffModuleInstance = window.PadiemChatAndroidHandoffModule.create({
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
        get setAuthFormError() { return setAuthFormError; },
        get loadAuthStatus() { return loadAuthStatus; },
        get closeAuthDialog() { return closeAuthDialog; },
        get uiT() { return uiT; },
        get authState() { return authState; },
      });
    }
    return androidHandoffModuleInstance;
  }
  function isAndroidWebView(...a) { return androidHandoffModule().isAndroidWebView(...a); }
  function stopAndroidHandoffPolling(...a) { return androidHandoffModule().stopAndroidHandoffPolling(...a); }
  function clearAndroidHandoff(...a) { return androidHandoffModule().clearAndroidHandoff(...a); }
  function androidHandoffPhaseKey(...a) { return androidHandoffModule().androidHandoffPhaseKey(...a); }
  function renderAndroidHandoff(...a) { return androidHandoffModule().renderAndroidHandoff(...a); }
  function claimAndroidHandoff(...a) { return androidHandoffModule().claimAndroidHandoff(...a); }
  function pollAndroidHandoff(...a) { return androidHandoffModule().pollAndroidHandoff(...a); }
  function startAndroidHandoffPolling(...a) { return androidHandoffModule().startAndroidHandoffPolling(...a); }
  function startAndroidHandoff(...a) { return androidHandoffModule().startAndroidHandoff(...a); }

  function syncAuthDialogMethods(...a) { return authModule().syncAuthDialogMethods(...a); }

  function openAuthDialog(...a) { return authModule().openAuthDialog(...a); }


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
    if (!isAndroidWebView()) return;
    const stored = readStoredAndroidHandoff();
    if (!stored) return;
    if (Date.now() >= stored.expiresAt) {
      try { window.sessionStorage.removeItem(ANDROID_HANDOFF_STORAGE_KEY); } catch (_) {}
      return;
    }
    if (stored.phase === "claiming") stored.phase = "waiting";
    androidHandoff = stored;
    renderAndroidHandoff();
    startAndroidHandoffPolling();
    pollAndroidHandoff();
  }

  function closeAuthDialog(...a) { return authModule().closeAuthDialog(...a); }

  // #5664: the Chat Python Worker can fail isolate startup with
  // `NoGilError: Attempted to use PyProxy when Python GIL not held`
  // (cloudflare/workerd#6624) and then answers a plain-text 5xx that no route
  // produced. That body never describes the account, so it must not be shown
  // as a rejected credential or a failed sign-in.
  const AUTH_SERVER_UNREACHABLE = "auth_server_unreachable";
  // One replay is safe only where the route makes it safe: the reset confirm is
  // guarded by its one-time token, whose atomic consume applies at most once,
  // and the failed request never reached the route. Every other auth write
  // keeps its single attempt.
  const AUTH_UNREACHABLE_RETRY_DELAY_MS = 600;

  function authServerUnreachableError(...a) { return authModule().authServerUnreachableError(...a); }

  function passwordAuthAnswer(...a) { return authModule().passwordAuthAnswer(...a); }

  function passwordAuthRequest(...a) { return authModule().passwordAuthRequest(...a); }

  function submitPasswordLogin(...a) { return authModule().submitPasswordLogin(...a); }

  function submitPasswordRegister(...a) { return authModule().submitPasswordRegister(...a); }

  // #5481: the lost-password flow. The entry link opens the request view, the
  // mailed one-time link opens the confirm view, and both keep the email the
  // member already typed. The token never travels in a query string: it
  // arrives in the URL fragment, which the browser does not send to the server.
  function setAuthStatusMessage(...a) { return authModule().setAuthStatusMessage(...a); }

  // A LoveTree sign-in that arrived here hands its pending ticket to the form the dialog
  // already submits. Same shape and same caution as the reset-link read below: the app shell
  // also loads inside curated VM harnesses without a location object, so this runs when the
  // dialog opens, never at load time. No wording or layout changes.
  function loveTreeHandoffFromLocation() {
    try {
      const raw = window.location.search || "";
      const match = /[?&]handoff=([A-Za-z0-9_.-]{1,1024})(?:&|$)/.exec(raw);
      return match ? match[1] : "";
    } catch (_) {
      return "";
    }
  }

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

  function passwordResetTokenFromLocation(...a) { return authModule().passwordResetTokenFromLocation(...a); }

  function clearPasswordResetFragment(...a) { return authModule().clearPasswordResetFragment(...a); }

  function showPasswordResetView(...a) { return authModule().showPasswordResetView(...a); }

  function hidePasswordResetViews(...a) { return authModule().hidePasswordResetViews(...a); }

  function openPasswordResetRequest(...a) { return authModule().openPasswordResetRequest(...a); }

  function openPasswordResetConfirm(...a) { return authModule().openPasswordResetConfirm(...a); }

  function closePasswordResetViews(...a) { return authModule().closePasswordResetViews(...a); }

  function submitPasswordResetRequest(...a) { return authModule().submitPasswordResetRequest(...a); }

  function submitPasswordResetConfirm(...a) { return authModule().submitPasswordResetConfirm(...a); }

  // #5434: the signed-in account changes its own password. The account is
  // never named by the browser: the server resolves it from the session.
  function openPasswordChangeDialog(...a) { return authModule().openPasswordChangeDialog(...a); }

  function closePasswordChangeDialog(...a) { return authModule().closePasswordChangeDialog(...a); }

  function submitPasswordChange(...a) { return authModule().submitPasswordChange(...a); }

  // Service-only and all-service deletion both require the exact account email
  // in the UI; the server repeats every session, origin, identity and admin check.
  function resetAccountDeleteConfirm(...a) { return authModule().resetAccountDeleteConfirm(...a); }

  function resetAccountSharedDeleteConfirm(...a) { return authModule().resetAccountSharedDeleteConfirm(...a); }

  function openAccountDeleteConfirm(...a) { return authModule().openAccountDeleteConfirm(...a); }

  function openAccountSharedDeleteConfirm(...a) { return authModule().openAccountSharedDeleteConfirm(...a); }

  function syncDeleteButton(button, inputElement) {
    if (!button) return;
    const typed = inputElement?.value ?? "";
    const email = authState.user && typeof authState.user.email === "string"
      ? authState.user.email : "";
    button.disabled = !email || typed !== email;
  }

  function syncAccountDeleteButton(...a) { return authModule().syncAccountDeleteButton(...a); }

  function syncAccountSharedDeleteButton(...a) { return authModule().syncAccountSharedDeleteButton(...a); }

  function submitAccountDelete(...a) { return authModule().submitAccountDelete(...a); }

  function renderHistorySkeleton(...a) { return historyModule().renderHistorySkeleton(...a); }

  function renderHistoryLoadFailed(...a) { return historyModule().renderHistoryLoadFailed(...a); }

  function fetchRecentConversations(...a) { return historyModule().fetchRecentConversations(...a); }

  function loadRecentConversations(...a) { return historyModule().loadRecentConversations(...a); }
  document.addEventListener("click", (event) => {
    if (event.target instanceof Element && event.target.closest(".history-actions")) return;
    historyList.querySelectorAll(".history-actions[open]").forEach((node) => { node.open = false; });
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    const expanded = historyList.querySelector(".history-actions[open]");
    if (!expanded) return;
    expanded.open = false;
    expanded.querySelector("summary")?.focus();
    event.stopPropagation();
  });
  // #7175: the server owns both the title and the pin. The sidebar only sends
  // the two reviewed fields and then re-reads the owner-scoped list, so the
  // group order and every label come from the same answer.
  const HISTORY_TITLE_MAX_CHARS = 80;

  function clearHistoryActionStatus(...a) { return historyModule().clearHistoryActionStatus(...a); }

  function showHistoryActionStatus(...a) { return historyModule().showHistoryActionStatus(...a); }

  function patchConversation(...a) { return historyModule().patchConversation(...a); }

  function focusHistoryConversation(...a) { return historyModule().focusHistoryConversation(...a); }

  function beginConversationRename(...a) { return historyModule().beginConversationRename(...a); }

  function deleteConversation(...a) { return historyModule().deleteConversation(...a); }
  async function fetchAuthStatusOnce() {
    const response = await fetch("/api/auth/status", { headers: { "Accept": "application/json" }, cache: "no-store" });
    const data = await response.json().catch(() => null);
    if (!response.ok || !data) throw new Error("auth status unavailable");
    return data;
  }
  let sharedRefreshTimer = null;
  function scheduleSharedRefresh() {
    if (sharedRefreshTimer) clearTimeout(sharedRefreshTimer);
    if (authState.shared_login_enabled !== true || authState.shared_session_present !== true) return;
    sharedRefreshTimer = setTimeout(async () => {
      try {
        const response = await fetch("/auth/shared/refresh", { method: "POST", headers: { "Accept": "application/json" }, cache: "no-store" });
        if (response.ok) await loadAuthStatus();
      } catch (_) { /* The next status read retries without treating failure as sign-out. */ }
    }, 14 * 60 * 1000);
  }
  function loadAuthStatus(...a) { return authModule().loadAuthStatus(...a); }
  // Background tabs may have their timers suspended beyond access expiry.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && authState.shared_login_enabled === true) void loadAuthStatus();
  });
  async function openSavedConversation(id) {
    if (!authState.authenticated || inFlight) return;
    const epoch = authViewEpoch;
    try {
      const response = await fetch(`/api/conversations/${encodeURIComponent(id)}`, { headers: { "Accept": "application/json" }, cache: "no-store" });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || !data.conversation || !Array.isArray(data.conversation.messages)) throw new Error(uiT("conversation-load-failed"));
      const savedProjectId = typeof data.conversation.project_id === "string" ? data.conversation.project_id : null;
      const restoredProject = savedProjectId ? await ensureProject(savedProjectId) : null;
      if (savedProjectId && !restoredProject) throw new Error(uiT("conversation-project-load-failed"));
      // Paint the list early, but preserve the existing canonical Claw lane
      // classification when the user opens a row before its labels arrive.
      const labels = clawConversationLabelsRead;
      if (labels && labels.epoch === epoch) await labels.promise;
      if (epoch !== authViewEpoch || !authState.authenticated) return false;
      clearAttachment();
      // #2505: the saved thread is the ONE conversation, so it is loaded into
      // the shared store. A thread that has Claw turns still opens on the Claw
      // screen (its last lane), and the other screen shows the same record.
      const isVerifiedClawThread = clawConversationIds.has(data.conversation.id);
      const targetProduct = isVerifiedClawThread ? PRODUCT_CLAW : PRODUCT_CHAT;
      messageList.replaceChildren();
      messageList.hidden = true;
      conversationState.resetProduct?.(targetProduct);
      conversationState.setProduct?.(targetProduct);
      conversationProduct = targetProduct;
      conversationState.setConversationId(data.conversation.id, targetProduct);
      activeProject = restoredProject;
      activeProjectFileCount = 0;
      renderProjectState();
      if (activeProject) refreshActiveProjectFileCount();
      if (isVerifiedClawThread) openClawWorkspace();
      showConversation({ preserveClaw: isVerifiedClawThread, restoreSaved: true });
      app.syncApprovedMemoryVisibility();
      syncClawRunHistoryVisibility();
      conversationArtifactContext?.show?.(data.conversation.id);
      if (isVerifiedClawThread) clawArtifactShownFor = data.conversation.id;
      data.conversation.messages.forEach((item) => {
        if (!item || typeof item.content !== "string") return;
        if (item.role === "user") addUserMessage(item.content, null, { restored: true });
        if (item.role === "assistant") renderStoredAssistant(item.content, item);
        if (item.role === "user" || item.role === "assistant") conversationState.appendMessage({ role: item.role, content: item.content }, targetProduct);
      });
      // #5895: keep showing a PC turn that is still running on the server, and
      // restore the thread once its stored answer lands.
      void resumeUnfinishedPcRun(data.conversation.id);
      // A restored conversation opens on its newest turn with follow resumed,
      // on the same shared Chat/Claw control.
      window.__padiemConversationMotion?.resume?.();
      closeSidebar();
      input.focus();
      return true;
    } catch (error) {
      setNote(error instanceof Error ? error.message : uiT("conversation-load-failed"), "error");
      return false;
    }
  }

  // #4471: the sidebar conversation search opens a hit through this loader
  // instead of a recent-list DOM row, so a hit outside the recent page still
  // restores with the same auth guard, inFlight lock, project restore and the
  // server-verified Claw set. Read-only handle: it grants no new authority.
  window.PadiemChatConversationOpener = Object.freeze({
    open: (conversationId) => openSavedConversation(conversationId),
  });

  // #4489: the Library opens a stored project file through that file's owning
  // project in the existing Project dialog, so project-file permission, the
  // files panel and every edit guard stay on the one canonical path. The project
  // resolves from the owner list or its existing authenticated project lookup;
  // a foreign or stale id opens nothing. This handle grants no new authority.
  window.PadiemChatProjectOpener = Object.freeze({
    openFile: async (projectId, fileId) => {
      if (!projectsReady || !authState.authenticated || inFlight) return false;
      const requestAuth = authState;
      const project = await ensureProject(projectId);
      if (!project || authState !== requestAuth || !authState.authenticated || inFlight) return false;
      openProjectDialog(project, fileId);
      return true;
    },
    open: (projectId) => {
      if (!projectsReady || !authState.authenticated || inFlight) return false;
      const project = projects.find((item) => item && item.id === projectId);
      if (!project) return false;
      openProjectDialog(project);
      return true;
    },
  });

    // Hark's private web XLSX intake creates a separate trusted owner-owned
  // work conversation. This explicit navigation never guesses that it was the
  // currently displayed chat or fabricates an assistant answer/file READ grant.
  window.addEventListener("padiem:claw-web-work-conversation-open", async (event) => {
    const detail = event?.detail;
    if (!authState.authenticated || inFlight || !detail
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
    const opened = await openSavedConversation(detail.conversationId);
    if (!opened) return;
    const notice = document.createElement("p");
    notice.className = "reference-note";
    notice.setAttribute("role", "status");
    notice.textContent = uiT(hasArtifact
      ? "claw-web-work-conversation-opened"
      : "claw-web-work-conversation-opened-read");
    messageList.prepend(notice);
    setNote(uiT("claw-web-work-conversation-note"));
  });

  async function requestCompletedAnswer(...a) { return streamingModule().requestCompletedAnswer(...a); }

  function applyStreamDone(...a) { return streamingModule().applyStreamDone(...a); }

  // Transport completion does not imply a completed durable PC run.
  const resolvedPcRuns = new Set();
  function showPcRuntimeStatus(...a) { return pcRunModule().showPcRuntimeStatus(...a); }
  async function waitForAcceptedPcRun(...a) { return pcRunModule().waitForAcceptedPcRun(...a); }

  const pcResultRecovery = window.PadiemChatPcRecovery?.create?.({
    fetchImpl: window.fetch.bind(window),
  }) || null;

  function pcWaitElapsed(...a) { return pcRunModule().pcWaitElapsed(...a); }
  async function findUnfinishedPcRun(...a) { return pcRunModule().findUnfinishedPcRun(...a); }
  async function resumeUnfinishedPcRun(...a) { return pcRunModule().resumeUnfinishedPcRun(...a); }
  function renderStoredPcAnswer(...a) { return pcRunModule().renderStoredPcAnswer(...a); }
  async function recoverStoredPcResult(...a) { return pcRunModule().recoverStoredPcResult(...a); }

  async function requestStreamingAnswer(...a) { return streamingModule().requestStreamingAnswer(...a); }

  function cancelActiveStream(...a) { return streamingModule().cancelActiveStream(...a); }

  // #4317: product-capabilities.js is loaded AFTER app.js and owns the tier
  // state. The universally available signed-in Free lane stays the default for
  // an account that never chose a tier.
  // #5222: an account that DID choose a tier keeps that choice across a
  // reload, so this page must not reset the selection to Free behind the
  // account's back. The restored value is always re-validated by the server
  // (member grade + administrator gate) before it is used.

  // #7216 R5 step 1: chat-settings-module.js owns the settings section body.
  function selectedProductTier(...a) { return settingsModule().selectedProductTier(...a); }

  // A failed PADIEM Custom request that needs the customer's key reopens the
  // existing model card. No second dialog and no generic fallback to a PADIEM
  // tier: the server's error message stays in the answer bubble.
  function handleCustomRequestFailure(error) {
    const code = error && typeof error.code === "string" ? error.code : "";
    if (code === "custom_credential_required" || code === CUSTOM_AUTH_FAILURE_CODE) {
      window.PadiemCustomSelection?.open?.();
      void window.PadiemCustomSelection?.refresh?.();
      return;
    }
    if (code === "unauthorized" && window.PadiemCustomSelection?.get?.()) {
      window.PadiemCustomSelection?.open?.();
      void loadAuthStatus();
    }
  }

  async function requestAnswer(...a) { return streamingModule().requestAnswer(...a); }
  // #3539: the generic B54 Claw composer runs on the canonical P01 Engine lane.
  // This predicate documents the product state that selects the lane: the Claw
  // shell with the explicit manual form hidden. It must be read at submit time,
  // BEFORE any conversation presentation transition.
  function clawGeneralRequestActive() {
    return shell.dataset.state === "claw" && !(clawManualForm && !clawManualForm.hidden);
  }

  // One-click answer regenerate for the action bar (outputs.js). Only the
  // latest completed answer may regenerate: the stored article, lifecycle
  // state and DOM position are all re-verified, and requestAnswer's inFlight
  // lock rejects any overlapping second call, so no duplicate or unintended
  // paid model call can fire. No user bubble is added; the same outbound
  // messages replay through the identical routing path.
  function storedRegenerateRequest(article) {
    const stored = lastCompletedAnswerRequest;
    if (!stored || stored.article !== article) return null;
    if (!article || !article.isConnected) return null;
    if (!window.PadiemChatLifecycle || !window.PadiemChatLifecycle.isCompleted(article)) return null;
    if (inFlight) return null;
    const list = document.getElementById("messageList");
    const items = list ? list.querySelectorAll(".assistant-message") : [];
    if (!items.length || items[items.length - 1] !== article) return null;
    return stored;
  }
  window.PadiemChatRegenerate = Object.freeze({
    available(article) {
      return storedRegenerateRequest(article) !== null;
    },
    regenerate(article) {
      const stored = storedRegenerateRequest(article);
      if (!stored) return false;
      void requestAnswer(stored.outboundMessages, stored.skill, stored.attachment, stored.contextSnapshot, stored.clawGeneralRequest);
      return true;
    },
  });

  // Owner decision 2026-11-05: Chat/Claw AI answers are signed-in only.
  // The composer stays editable; pressing send opens the existing login
  // dialog, keeps the typed text, and never leaves a model request behind.
  // The server is the final authority and answers a bypassing guest with 401
  // login_required. A mock/preview deployment that cannot authenticate keeps
  // its CI harness behavior through the server-owned flag.
  function requireSessionForModelUse(...a) { return authModule().requireSessionForModelUse(...a); }

  async function submitPrompt(text, selectedSkill) {
    const prompt = text.trim();
    if (!prompt || inFlight) return;
    if (!requireSessionForModelUse()) return;
    // #3539: snapshot the canonical lane before changing presentation;
    // #3931: keep a general Claw request in the same Claw conversation.
    // Neither UI state nor the selected model ID may authorize fallback.
    const clawGeneralRequest = clawGeneralRequestActive();
    // Chat/Claw separation: the lane decides the product. The conversation id, the turn
    // store and the skill all come from that product's own slot, so a Claw
    // request never carries the Chat conversation id and a Chat request never
    // carries the Claw one. This is an immutable submit-time snapshot.
    const product = clawGeneralRequest ? PRODUCT_CLAW : PRODUCT_CHAT;
    conversationState.setProduct?.(product);
    if (selectedSkill) conversationState.setSkill(selectedSkill);
    const attachmentSnapshot = selectedAttachments;
    const contextSnapshot = { product, conversationId: conversationState.getConversationId(product), project: activeProject };
    // PADIEM Custom is text-only on both Chat and Claw. Refuse attachments
    // here, with the typed prompt preserved.
    const customSelected = Boolean(window.PadiemCustomSelection?.get?.());
    if (customSelected && attachmentSnapshot.length) {
      setNote(uiT("custom-text-only"), "error");
      return;
    }
    // #6828: grade-only Claw execution. The grade travels as `tier` and the
    // server resolves the grade route; no per-request model id is ever sent.
    contextSnapshot.selectedModelId = "";
    showConversation({ preserveClaw: clawGeneralRequest });
    addUserMessage(prompt, attachmentSnapshot);
    input.value = "";
    // #5561: the composer is empty again, so the primary action slot returns
    // to the voice waveform.
    updateComposer();
    const outbound = conversationState.outboundWithUser(prompt);
    const success = await requestAnswer(outbound, conversationState.getSkill(), attachmentSnapshot, contextSnapshot, clawGeneralRequest);
    if (success && selectedAttachments === attachmentSnapshot) clearAttachment();
  }

  function setSidebarCollapsed(...a) { return sidebarModule().setSidebarCollapsed(...a); }
  function closeSidebar(...a) { return sidebarModule().closeSidebar(...a); }
  function openSidebar(...a) { return sidebarModule().openSidebar(...a); }
  function openSettings(...a) { return settingsModule().openSettings(...a); }
  function closeSettings(...a) { return settingsModule().closeSettings(...a); }
  const advancedSettingsView = document.getElementById("advancedSettingsView");
  // The full page opens on top of the screen the user came from (home, chat or
  // claw). Its back entry must return there instead of assuming home.
  let advancedSettingsReturnState = null;
  function openAdvancedSettingsView(...a) { return settingsModule().openAdvancedSettingsView(...a); }
  function closeAdvancedSettingsView(...a) { return settingsModule().closeAdvancedSettingsView(...a); }

  window.addEventListener("padiem:tierchange", () => {
    if (shell.dataset.state === "claw") shell.dataset.clawTier = selectedProductTier();
  });
  input.addEventListener("input", updateComposer);
  // #3084: Korean IME regression protection. While a Hangul/IME composition is
  // active the browser still reports key === "Enter" for the candidate-confirm
  // key, so submitting on it would send a half-composed word. The guard below
  // is the shared pure decision (claw-local-handoff.js) plus an explicit
  // composition tracker for engines that omit event.isComposing.
  const localHandoffModule = window.PadiemClawLocalHandoff;
  // All three products load the canonical keyboard guard. The historic
  // handoff guard remains for isolated older fixture/browser pages.
  const composerInputModule = window.PadiemConversationComposer || localHandoffModule;
  const composerComposition = composerInputModule
    ? composerInputModule.createCompositionGuard()
    : null;
  input.addEventListener("compositionstart", () => composerComposition?.start());
  input.addEventListener("compositionupdate", () => composerComposition?.update());
  input.addEventListener("compositionend", () => composerComposition?.end());
  input.addEventListener("keydown", (event) => {
    const shouldSubmit = composerInputModule
      ? composerInputModule.shouldSubmitOnEnter(event, composerComposition)
      : false; // Never submit Hangul IME text with an unavailable guard.
    if (!shouldSubmit) return;
    event.preventDefault();
    if (!sendButton.disabled) form.requestSubmit();
  });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    // #3531: the shared composer always submits to the general Claw
    // conversation, in every shell state. The quotation/document workflow
    // runs only via the manual form's own explicit draft submit button;
    // a generic request must never auto-enter it through the composer.
    // #4647: the meeting workbench consumes its own explicit meeting-setup
    // command from its own capture-phase listener on this same form, so this
    // handler keeps no shell-state fork and every other prompt is unaffected.
    submitPrompt(input.value);
  });
  cancelStreamButton.addEventListener("click", cancelActiveStream);
  attachmentButton.addEventListener("click", () => { if (!inFlight) attachmentFileInput.click(); });
  documentStarterButton.addEventListener("click", () => { if (!inFlight) attachmentFileInput.click(); });
  const documentFormatsToggle = document.getElementById("documentFormatsToggle");
  const documentFormatsPanel = document.getElementById("documentFormatsPanel");
  if (documentFormatsToggle && documentFormatsPanel) {
    documentFormatsToggle.addEventListener("click", () => {
      const show = documentFormatsPanel.hidden;
      documentFormatsPanel.hidden = !show;
      documentFormatsToggle.setAttribute("aria-expanded", show ? "true" : "false");
    });
    document.addEventListener("click", (event) => {
      if (documentFormatsPanel.hidden || (event.target.closest && event.target.closest(".document-starter-shell"))) return;
      documentFormatsPanel.hidden = true;
      documentFormatsToggle.setAttribute("aria-expanded", "false");
    });
  }
  attachmentFileInput.addEventListener("change", () => {
    const files = Array.from(attachmentFileInput.files || []);
    if (files.length) void addAttachmentFiles(files);
  });
  // #261102: drag and drop also attaches several files at once.
  const composerForm = document.getElementById("composerForm");
  if (composerForm) {
    composerForm.addEventListener("dragover", (event) => {
      if (inFlight) return;
      event.preventDefault();
      if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
    });
    composerForm.addEventListener("drop", (event) => {
      if (inFlight) return;
      event.preventDefault();
      const files = event.dataTransfer ? Array.from(event.dataTransfer.files || []) : [];
      if (files.length) void addAttachmentFiles(files);
    });
  }
  if (projectsNavButton) projectsNavButton.addEventListener("click", () => {
    if (!projectsReady) return;
    if (projects.length === 0) openProjectDialog();
    else projectsSection.scrollIntoView({ block: "nearest", behavior: "smooth" });
  });
  projectCreateButton.addEventListener("click", () => openProjectDialog());
  editProjectButton.addEventListener("click", () => { if (activeProject) openProjectDialog(activeProject); });
  exitProjectButton.addEventListener("click", exitProject);
  projectDialogClose.addEventListener("click", closeProjectDialog);
  projectDialogCancel.addEventListener("click", closeProjectDialog);
  projectForm.addEventListener("submit", saveProject);
  projectDeleteButton.addEventListener("click", deleteProject);
  projectFileInput.addEventListener("change", () => {
    const [file] = projectFileInput.files || [];
    addProjectFile(file);
  });
  projectDialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    closeProjectDialog();
  });
  // #5560: one sign-out implementation, reached from the sidebar session
  // button and from Settings > Account. The server session invalidation and
  // the local conversation reset are the same in both paths.
  function signOutCurrentAccount(...a) { return authModule().signOutCurrentAccount(...a); }
  const guestLoginEntryButton = document.getElementById("guestLoginEntryButton");
  if (guestLoginEntryButton) guestLoginEntryButton.addEventListener("click", openAuthDialog);
  loginButton.addEventListener("click", async () => {
    if (!authState.ready) {
      // #5479: the session state is unknown, so the button retries it instead of
      // doing nothing. A dead entry point is what locked people out when the
      // Chat Worker failed to answer /api/auth/status.
      await loadAuthStatus();
      if (!authState.ready) {
        setNote(uiT(authState.status_reachable === false ? "login-unreachable-title" : "login-unavailable-title"), "error");
        return;
      }
    }
    if (!authState.authenticated) {
      openAuthDialog();
      return;
    }
    await signOutCurrentAccount();
  });
  const settingsAdvancedOpen = document.getElementById("settingsAdvancedOpen");
  if (settingsAdvancedOpen) settingsAdvancedOpen.addEventListener("click", () => {
    closeSettings();
    openAdvancedSettingsView();
  });
  const advancedSettingsBack = document.getElementById("advancedSettingsBack");
  if (advancedSettingsBack) advancedSettingsBack.addEventListener("click", () => { closeAdvancedSettingsView(); });
  // Escape takes the same close path as the back entry. An open dialog inside
  // the page (password change, deletes) keeps Escape for itself.
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || event.isComposing) return;
    if (!advancedSettingsView || advancedSettingsView.hidden) return;
    if (document.querySelector("dialog[open]")) return;
    closeAdvancedSettingsView();
  });
  const advancedMenuButtons = [...document.querySelectorAll(".advanced-menu-link")];
  const advancedPageBlocks = [...document.querySelectorAll(".advanced-page-block")];
  function selectAdvancedMenu(key) {
    for (const button of advancedMenuButtons) {
      button.classList.toggle("selected", button.dataset.advancedMenu === key);
    }
    for (const block of advancedPageBlocks) {
      block.hidden = block.dataset.advancedBlock !== key;
    }
  }
  for (const button of advancedMenuButtons) {
    button.addEventListener("click", () => selectAdvancedMenu(button.dataset.advancedMenu));
  }
  if (settingsLogoutButton) {
    settingsLogoutButton.addEventListener("click", async () => {
      if (!authState.ready || !authState.authenticated) return;
      settingsLogoutButton.disabled = true;
      settingsLogoutButton.setAttribute("aria-disabled", "true");
      settingsLogoutButton.setAttribute("aria-busy", "true");
      try {
        closeSettings();
        await signOutCurrentAccount();
      } finally {
        settingsLogoutButton.disabled = false;
        settingsLogoutButton.setAttribute("aria-disabled", "false");
        settingsLogoutButton.removeAttribute("aria-busy");
      }
    });
  }
  if (authDialogClose) authDialogClose.addEventListener("click", closeAuthDialog);
  if (authDialog) {
    authDialog.addEventListener("cancel", (event) => {
      event.preventDefault();
      closeAuthDialog();
    });
  }
  if (googleLoginButton) {
    googleLoginButton.addEventListener("click", () => {
      if (!authMethodEnabled("google")) return;
      if (isAndroidWebView()) {
        startAndroidHandoff();
        return;
      }
      window.location.assign("/auth/google/start");
    });
  }
  androidHandoffModule().wireAndroidHandoffListeners();
  if (passwordLoginForm) passwordLoginForm.addEventListener("submit", submitPasswordLogin);
  if (passwordRegisterForm) passwordRegisterForm.addEventListener("submit", submitPasswordRegister);
  if (passwordResetOpen) {
    passwordResetOpen.addEventListener("click", openPasswordResetRequest);
  }
  if (passwordResetRequestForm) {
    passwordResetRequestForm.addEventListener("submit", submitPasswordResetRequest);
  }
  if (passwordResetConfirmForm) {
    passwordResetConfirmForm.addEventListener("submit", submitPasswordResetConfirm);
  }
  if (passwordResetBack) {
    passwordResetBack.addEventListener("click", () => {
      hidePasswordResetViews();
      syncAuthDialogMethods();
    });
  }
  if (passwordResetConfirmBack) {
    passwordResetConfirmBack.addEventListener("click", () => {
      hidePasswordResetViews();
      syncAuthDialogMethods();
    });
  }
  if (passwordChangeForm) passwordChangeForm.addEventListener("submit", submitPasswordChange);
  if (passwordChangeOpen) passwordChangeOpen.addEventListener("click", openPasswordChangeDialog);
  if (accountDeleteOpen) accountDeleteOpen.addEventListener("click", openAccountDeleteConfirm);
  if (accountSharedDeleteOpen) {
    accountSharedDeleteOpen.addEventListener("click", openAccountSharedDeleteConfirm);
  }
  if (accountDeleteConfirmEmail) {
    accountDeleteConfirmEmail.addEventListener("input", syncAccountDeleteButton);
  }
  if (accountDeleteButton) {
    accountDeleteButton.addEventListener("click", () => submitAccountDelete(false));
  }
  if (accountSharedDeleteConfirmEmail) {
    accountSharedDeleteConfirmEmail.addEventListener("input", syncAccountSharedDeleteButton);
  }
  if (accountSharedDeleteButton) {
    accountSharedDeleteButton.addEventListener("click", () => submitAccountDelete(true));
  }
  if (passwordChangeDialogClose) passwordChangeDialogClose.addEventListener("click", closePasswordChangeDialog);
  if (passwordChangeDialog) {
    passwordChangeDialog.addEventListener("cancel", (event) => {
      event.preventDefault();
      closePasswordChangeDialog();
    });
  }
  document.querySelectorAll("[data-prompt]").forEach((button) => button.addEventListener("click", () => {
    submitPrompt(button.dataset.prompt || "", button.dataset.skill || "auto");
    closeSidebar();
  }));
  newChatButton.addEventListener("click", () => resetConversation(true));
  // The visible account name/avatar is the one-step Settings entry.
  // Reuse the existing settings action; do not create a second settings flow.
  profileToggle.addEventListener("click", () => {
    if (accountContainer?.hidden) return;
    closeProfilePanel();
    settingsButton.click();
  });
  profileSettingsAction.addEventListener("click", () => {
    closeProfilePanel();
    settingsButton.click(); // keep the existing settings-dialog authority
  });
  document.addEventListener("pointerdown", (event) => {
    if (!profilePanel.hidden && !accountContainer?.contains(event.target)) closeProfilePanel();
  });
  settingsButton.addEventListener("click", () => { closeProfilePanel(); openSettings(); });
  settingsDialog.addEventListener("close", () => {
    settingsButton.setAttribute("aria-expanded", "false");
    profileToggle.setAttribute("aria-expanded", "false");
  });
  settingsDialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    closeSettings();
  });
  // The dialog element is the panel itself, so a backdrop click reports the
  // dialog as the target. Any click inside the panel hits a descendant first.
  settingsDialog.addEventListener("click", (event) => {
    if (event.target === settingsDialog) closeSettings();
  });
  settingsCloseButton.addEventListener("click", closeSettings);
  sidebarCollapseButton?.addEventListener("click", () => setSidebarCollapsed(true));
  sidebarRestoreButton?.addEventListener("click", () => setSidebarCollapsed(false));
  mobileMenu.addEventListener("click", openSidebar);
  mobileClose.addEventListener("click", closeSidebar);
  sidebarScrim.addEventListener("click", closeSidebar);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !profilePanel.hidden) {
      closeProfilePanel(true);
      return;
    }
    if (event.key === "Escape" && shell.classList.contains("sidebar-open")) closeSidebar();
  });
  window.addEventListener("padiem:localechange", () => {
    applyAuthState(authState);
    renderAndroidHandoff();
    setNavActive();
    if (projectsReady) renderProjects();
    renderProjectState();
    if (!selectedAttachments.length) setNote(idleNote());
    syncComposerForClaw(shell.dataset.state === "claw");
      });
  window.addEventListener("padiem:attachmentcapabilitychange", () => {
    if (!selectedAttachments.length) setNote(idleNote());
  });

  // Claw first-class workspace & MVP usability wiring (#2299)
  const clawNavButton = document.getElementById("clawNavButton");
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
  const clawResultKind = document.getElementById("clawResultKind");
  const clawGenerateBtn = document.getElementById("clawGenerateBtn");
  const clawExecuteButton = document.getElementById("clawExecuteButton");
  const clawResultBadge = document.getElementById("clawResultBadge");
  const clawResultDocx = document.getElementById("clawResultDocx");
  const clawApprovalActions = document.getElementById("clawApprovalActions");
  const clawStatus = document.getElementById("clawStatus");
  const clawRetryBox = document.getElementById("clawRetryBox");
  const clawRetryCopy = document.getElementById("clawRetryCopy");
  const clawRetryButton = document.getElementById("clawRetryButton");
  const clawRetryHint = document.getElementById("clawRetryHint");
  const clawRequestEcho = document.getElementById("clawRequestEcho");
  const clawRequestEchoText = document.getElementById("clawRequestEchoText");
  const clawArtifactMeta = document.getElementById("clawArtifactMeta");
  const clawArtifactName = document.getElementById("clawArtifactName");
  const clawArtifactSize = document.getElementById("clawArtifactSize");
  const clawResultSuccessNote = document.getElementById("clawResultSuccessNote");
  const clawResultHint = document.getElementById("clawResultHint");
  const clawExecuteHint = document.getElementById("clawExecuteHint");
  const clawWait = document.getElementById("clawWait");

  let clawInFlight = false;
  let clawLastAction = clawAction?.value || "quote";
  // Pre-dispatch execute recovery state (#2760). Owned by the recovery block below.
  let clawRetrySeconds = 0;
  let clawRetryTimer = null;
  // #3382: an ambiguous manual-execute failure may already have reached Engine,
  // and a P01 request carries no idempotency key, so the surface cannot tell
  // "never ran" from "already ran". Uncertainty is tracked PER REQUEST IDENTITY,
  // not as one flag: composing different work unblocks only that new request, and
  // restoring an uncertain one re-blocks it. The draft/preview and chat lanes are
  // never gated by this set.
  const clawUncertainKeys = new Set();
  let clawLastDispatchKey = "";
  // In-flight elapsed wait state (#2763). Owned by the wait block below.
  let clawWaitStartedAt = 0;
  let clawWaitTimer = null;
  let clawWaitRevealed = false;
  let clawWaitAnnouncedStage = 0;
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

  function invalidateClawApprovalSession(...a) { return authModule().invalidateClawApprovalSession(...a); }

  function noteClawApprovalSession(...a) { return authModule().noteClawApprovalSession(...a); }

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

  function clawT(...a) { return coreModule().clawT(...a); }
  function localeOr(...a) { return coreModule().localeOr(...a); }

  // #7216 R5 A4 (claw-status): Claw status, pre-dispatch retry, and the
  // in-flight elapsed wait live in chat-claw-status-module.js. app.js keeps
  // one-line forwarders and reads/writes closure state live via getters and setters.
  let clawStatusModuleInstance = null;
  function clawStatusModule() {
    if (!clawStatusModuleInstance) {
      clawStatusModuleInstance = window.PadiemChatClawStatusModule.create({
        get input() { return input; },
        get shell() { return shell; },
        get clawStatus() { return clawStatus; },
        get clawResultArea() { return clawResultArea; },
        get clawGenerateBtn() { return clawGenerateBtn; },
        get clawExecuteButton() { return clawExecuteButton; },
        get clawChannel() { return clawChannel; },
        get clawAction() { return clawAction; },
        get clawSender() { return clawSender; },
        get clawRetryBox() { return clawRetryBox; },
        get clawRetryCopy() { return clawRetryCopy; },
        get clawRetryButton() { return clawRetryButton; },
        get clawRetryHint() { return clawRetryHint; },
        get clawWait() { return clawWait; },
        get clawWorkspace() { return clawWorkspace; },
        get clawInFlight() { return clawInFlight; },
        set clawInFlight(value) { clawInFlight = value; },
        get clawRetrySeconds() { return clawRetrySeconds; },
        set clawRetrySeconds(value) { clawRetrySeconds = value; },
        get clawRetryTimer() { return clawRetryTimer; },
        set clawRetryTimer(value) { clawRetryTimer = value; },
        get clawUncertainKeys() { return clawUncertainKeys; },
        get clawLastDispatchKey() { return clawLastDispatchKey; },
        get clawWaitStartedAt() { return clawWaitStartedAt; },
        set clawWaitStartedAt(value) { clawWaitStartedAt = value; },
        get clawWaitTimer() { return clawWaitTimer; },
        set clawWaitTimer(value) { clawWaitTimer = value; },
        get clawWaitRevealed() { return clawWaitRevealed; },
        set clawWaitRevealed(value) { clawWaitRevealed = value; },
        get clawWaitAnnouncedStage() { return clawWaitAnnouncedStage; },
        set clawWaitAnnouncedStage(value) { clawWaitAnnouncedStage = value; },
        get clawT() { return clawT; },
        get localeOr() { return localeOr; },
        get selectedProductTier() { return selectedProductTier; },
        get conversationState() { return conversationState; },
      });
    }
    return clawStatusModuleInstance;
  }

  function syncComposerForClaw(...a) { return clawStatusModule().syncComposerForClaw(...a); }
  function setClawStatus(...a) { return clawStatusModule().setClawStatus(...a); }
  function setClawAreaState(...a) { return clawStatusModule().setClawAreaState(...a); }
  function setClawButtonsBusy(...a) { return clawStatusModule().setClawButtonsBusy(...a); }
  function clawRetryRemaining(...a) { return clawStatusModule().clawRetryRemaining(...a); }
  function clawVisibleExecutePayload(...a) { return clawStatusModule().clawVisibleExecutePayload(...a); }
  function clawExecuteWireKey(...a) { return clawStatusModule().clawExecuteWireKey(...a); }
  function clawCurrentDispatchIsUncertain(...a) { return clawStatusModule().clawCurrentDispatchIsUncertain(...a); }
  function noteClawContentEdited(...a) { return clawStatusModule().noteClawContentEdited(...a); }
  function clawRetryAfterFromResponse(...a) { return clawStatusModule().clawRetryAfterFromResponse(...a); }
  function isAmbiguousClawFailure(...a) { return clawStatusModule().isAmbiguousClawFailure(...a); }
  function clearClawRecovery(...a) { return clawStatusModule().clearClawRecovery(...a); }
  function renderClawRetryBox(...a) { return clawStatusModule().renderClawRetryBox(...a); }
  function beginClawRetryCooldown(...a) { return clawStatusModule().beginClawRetryCooldown(...a); }
  function showClawAmbiguousRecoveryHint(...a) { return clawStatusModule().showClawAmbiguousRecoveryHint(...a); }
  function applyClawWaitStageCopy(...a) { return clawStatusModule().applyClawWaitStageCopy(...a); }
  function renderClawWait(...a) { return clawStatusModule().renderClawWait(...a); }
  function beginClawWait(...a) { return clawStatusModule().beginClawWait(...a); }
  function clearClawWait(...a) { return clawStatusModule().clearClawWait(...a); }

  // A generated document always retains its original bounded download action.
  // #3932 preview is separate and only appears for an actual PDF receipt,
  // with fresh server-side tenant validation and real PDF bytes.
  // #7216 R5 A5a (claw-run): Claw manual run artifacts, approval controls, and the
  // single execute entry point live in chat-claw-run-module.js. app.js keeps one-line
  // forwarders and reads/writes closure state live via getters and setters.
  let clawRunModuleInstance = null;
  function clawRunModule() {
    if (!clawRunModuleInstance) {
      clawRunModuleInstance = window.PadiemChatClawRunModule.create({
        get clawResultDocx() { return clawResultDocx; },
        get clawArtifactMeta() { return clawArtifactMeta; },
        get clawArtifactName() { return clawArtifactName; },
        get clawArtifactSize() { return clawArtifactSize; },
        get clawResultSuccessNote() { return clawResultSuccessNote; },
        get clawResultEmpty() { return clawResultEmpty; },
        get clawResultHint() { return clawResultHint; },
        get clawResultCard() { return clawResultCard; },
        get clawResultKind() { return clawResultKind; },
        get clawResultBadge() { return clawResultBadge; },
        get clawApprovalActions() { return clawApprovalActions; },
        get clawResultPreview() { return clawResultPreview; },
        get clawRequestEcho() { return clawRequestEcho; },
        get clawRequestEchoText() { return clawRequestEchoText; },
        get clawExecuteButton() { return clawExecuteButton; },
        get input() { return input; },
        get clawT() { return clawT; },
        get setClawStatus() { return setClawStatus; },
        get setClawAreaState() { return setClawAreaState; },
        get setClawButtonsBusy() { return setClawButtonsBusy; },
        get clawBoundedRefusalCopy() { return clawBoundedRefusalCopy; },
        get approvalDecisionErrorMessage() { return approvalDecisionErrorMessage; },
        get mappedUiError() { return mappedUiError; },
        get safeLocalUiMessage() { return safeLocalUiMessage; },
        get failureCodeNote() { return failureCodeNote; },
        get loadClawRunHistory() { return loadClawRunHistory; },
        get clawRetryRemaining() { return clawRetryRemaining; },
        get clawCurrentDispatchIsUncertain() { return clawCurrentDispatchIsUncertain; },
        get clawVisibleExecutePayload() { return clawVisibleExecutePayload; },
        get clawExecuteWireKey() { return clawExecuteWireKey; },
        get clearClawRecovery() { return clearClawRecovery; },
        get clawRetryAfterFromResponse() { return clawRetryAfterFromResponse; },
        get isAmbiguousClawFailure() { return isAmbiguousClawFailure; },
        get beginClawRetryCooldown() { return beginClawRetryCooldown; },
        get showClawAmbiguousRecoveryHint() { return showClawAmbiguousRecoveryHint; },
        get beginClawWait() { return beginClawWait; },
        get clearClawWait() { return clearClawWait; },
        get conversationState() { return conversationState; },
        get PRODUCT_CLAW() { return PRODUCT_CLAW; },
        get authState() { return authState; },
        get chatTransport() { return chatTransport; },
        get app() { return app; },
        get clawApprovalInFlight() { return clawApprovalInFlight; },
        set clawApprovalInFlight(value) { clawApprovalInFlight = value; },
        get clawApprovalEpoch() { return clawApprovalEpoch; },
        get clawInFlight() { return clawInFlight; },
        set clawLastDispatchKey(value) { clawLastDispatchKey = value; },
      });
    }
    return clawRunModuleInstance;
  }
  function setClawDocumentAction(...a) { return clawRunModule().setClawDocumentAction(...a); }
  function clearClawArtifact(...a) { return clawRunModule().clearClawArtifact(...a); }
  function formatClawBytes(...a) { return clawRunModule().formatClawBytes(...a); }
  function renderClawArtifactMeta(...a) { return clawRunModule().renderClawArtifactMeta(...a); }
  function safeClawErrorMessage(...a) { return clawRunModule().safeClawErrorMessage(...a); }
  function downloadClawArtifact(...a) { return clawRunModule().downloadClawArtifact(...a); }
  function revealClawCard(...a) { return clawRunModule().revealClawCard(...a); }
  function setApprovalControlsBusy(...a) { return clawRunModule().setApprovalControlsBusy(...a); }
  function renderClawApprovalControls(...a) { return clawRunModule().renderClawApprovalControls(...a); }
  function clearImmediateApprovalControls(...a) { return clawRunModule().clearImmediateApprovalControls(...a); }
  function applyImmediateApprovalDecision(...a) { return clawRunModule().applyImmediateApprovalDecision(...a); }
  function renderClawRequestEcho(...a) { return clawRunModule().renderClawRequestEcho(...a); }
  function clawClaimDispatchKey(...a) { return clawRunModule().clawClaimDispatchKey(...a); }
  function releaseClawDispatchKey(...a) { return clawRunModule().releaseClawDispatchKey(...a); }
  function runClawExecution(...a) { return clawRunModule().runClawExecution(...a); }

  // #7216 R5 A5b (claw-form): the manual form submit/preview handler and the
  // execute/retry control wiring live in chat-claw-form-module.js. app.js keeps
  // the declaration block and calls the wire functions at the original
  // registration positions; deps getters read the closure variables live.
  let clawFormModuleInstance = null;
  function clawFormModule() {
    if (!clawFormModuleInstance) {
      clawFormModuleInstance = window.PadiemChatClawFormModule.create({
        get clawManualForm() { return clawManualForm; },
        get clawResultDocx() { return clawResultDocx; },
        get clawResultCard() { return clawResultCard; },
        get clawResultEmpty() { return clawResultEmpty; },
        get clawResultHint() { return clawResultHint; },
        get clawResultPreview() { return clawResultPreview; },
        get clawChannel() { return clawChannel; },
        get clawAction() { return clawAction; },
        get clawSender() { return clawSender; },
        get clawExecuteButton() { return clawExecuteButton; },
        get clawRetryButton() { return clawRetryButton; },
        get input() { return input; },
        get clawInFlight() { return clawInFlight; },
        get downloadClawArtifact() { return downloadClawArtifact; },
        get clearClawArtifact() { return clearClawArtifact; },
        get clawT() { return clawT; },
        get setClawStatus() { return setClawStatus; },
        get setClawAreaState() { return setClawAreaState; },
        get setClawButtonsBusy() { return setClawButtonsBusy; },
        get renderClawRequestEcho() { return renderClawRequestEcho; },
        get revealClawCard() { return revealClawCard; },
        get runClawExecution() { return runClawExecution; },
        get noteClawContentEdited() { return noteClawContentEdited; },
        get app() { return app; },
      });
    }
    return clawFormModuleInstance;
  }


  automationForm.wireEditListeners();


  automationForm.wireCreateListeners();


  automation.wireViewListeners();
  function openClawWorkspace() {
    // #3531: Claw opens on the general conversation view. The document
    // workflow (manual form, workflow chrome) stays hidden until the user
    // explicitly enters it via openClawManual.
    if (!clawWorkspace) return;
    shell.dataset.state = "claw";
    // #2505: entering Claw selects the Claw lane and keeps the same conversation,
    // so the thread continues instead of restarting.
    switchConversationProduct(PRODUCT_CLAW);
    clawWorkspace.dataset.view = "general";
    // The shared Chat first-use hero also introduces Claw when the
    // existing conversation has not started. Do not reset live messages.
    if (messageList.hidden && messageList.children.length === 0) emptyState.hidden = false;
    if (app.clawAutomation) app.clawAutomation.hidden = true;
    if (clawManualForm) clawManualForm.hidden = true;
    if (clawResultArea) clawResultArea.hidden = false;
    setNavActive();
    input.focus();
    closeSidebar();
    app.syncApprovedMemoryVisibility();
    syncClawRunHistoryVisibility();
  }

  function openChatWorkspace() {
    // #7173: back to the Chat lane on the same conversation (#2505); the Util
    // screen owns its own state and hash, and hides itself before this runs.
    shell.dataset.state = "home";
    switchConversationProduct(PRODUCT_CHAT);
    setNavActive();
    if (input) input.focus();
    closeSidebar();
  }

  // #7173: the Chat | Claw | Util app switch reuses the two existing screen
  // entries so the Util screen never re-implements shell state. Kept next to
  // the functions it names (some Node harnesses evaluate a source slice).
  window.PadiemAppSwitch = Object.freeze({
    openChat: openChatWorkspace,
    openClaw: openClawWorkspace,
  });

  function openClawManual() {
    // Explicit entry into the document/quotation workflow only. The manual
    // form and its workflow chrome are never shown by default.
    if (!clawWorkspace) return;
    shell.dataset.state = "claw";
    // Chat/Claw separation: the document workflow belongs to the Claw conversation.
    switchConversationProduct(PRODUCT_CLAW);
    clawWorkspace.dataset.view = "manual";
    if (app.clawAutomation) app.clawAutomation.hidden = true;
    if (clawManualForm) clawManualForm.hidden = false;
    if (clawResultArea) clawResultArea.hidden = false;
    setNavActive();
    input.focus();
    closeSidebar();
    app.syncApprovedMemoryVisibility();
    syncClawRunHistoryVisibility();
  }

  function openClawRunTarget(runId) {
    pendingClawRunFocusId = runId;
    openClawWorkspace();
  }

  window.addEventListener("padiem:calendar-open-link", (event) => {
    const detail = event && event.detail && typeof event.detail === "object" ? event.detail : {};
    const kind = typeof detail.kind === "string" ? detail.kind : "";
    const targetId = typeof detail.targetId === "string" ? detail.targetId : "";
    if (kind === "claw_session" && /^chat_[0-9a-f]{32}$/.test(targetId)) {
      void openSavedConversation(targetId);
      return;
    }
        if (kind === "run" && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(targetId)) {
      openClawRunTarget(targetId);
      return;
    }
    if (kind === "artifact" && /^doc_[A-Za-z0-9]{32}$/.test(targetId)) {
      openClawWorkspace();
      void downloadClawArtifact(targetId, "");
    }
  });

  // #3222 Web Claw connector truth. The browser consumes the existing
  // read-only #2830 projection; it never becomes a connector/OAuth authority.
  const connectorsNavButton = document.getElementById("connectorsNavButton");
  const connectorsDialog = document.getElementById("connectorsDialog");
  const connectorsDialogClose = document.getElementById("connectorsDialogClose");
  const connectorsLoading = document.getElementById("connectorsLoading");
  const connectorsError = document.getElementById("connectorsError");
  const connectorsRetry = document.getElementById("connectorsRetry");
  const GOOGLE_CALENDAR_CONNECTOR = "google-calendar";
  // #3289: the reviewed Google Drive READ-only connect handoff reuses the
  // same reviewed ticket endpoint; only the reviewed connector id differs.
  const GOOGLE_DRIVE_CONNECTOR = "google-drive";
  const GOOGLE_DRIVE_TICKET_ENDPOINT = "/api/connectors/google/ticket";
  // #7088: Gmail joins the same reviewed READ-only connect handoff with its
  // already-registered readonly scope set.
  const GOOGLE_GMAIL_CONNECTOR = "gmail";
  const GOOGLE_GMAIL_TICKET_ENDPOINT = "/api/connectors/google/ticket";
  const GOOGLE_CALENDAR_TICKET_ENDPOINT = "/api/connectors/google/ticket";
  const GOOGLE_CALENDAR_READ_ACTIVATION_ENDPOINT = "/api/connectors/google/calendar/activate-read";
  const CONNECTOR_STATUS_IDS = new Set([
    "connector:google:drive@1",
    "connector:google:gmail@1",
    "connector:telegram:bot@1",
    "connector:slack:workspace@1",
    "connector:google:calendar@1",
  ]);
  let connectorStatusInFlight = false;
  let googleConnectorConnectInFlight = false;
  // In-session Calendar READ grant truth (#2952). "unknown" until this session
  // activates it; the status projection carries no persisted grant field, so
  // nothing here claims a grant the server has not just confirmed.
  let googleCalendarReadState = "unknown";
  let googleCalendarReadActivationAfterConnectReturn = false;

  function setConnectorCopy(element, key) {
    if (!element) return;
    element.dataset.localeKey = key;
    element.textContent = uiT(key);
  }

  function connectorSupportKey(value) {
    if (value === "complete") return "connectors-support-complete";
    if (value === "source_ready") return "connectors-support-source-ready";
    if (value === "deferred") return "connectors-support-deferred";
    return "connectors-status-unavailable";
  }

  function connectorWorkspaceKey(value) {
    if (value === "connected") return "connectors-workspace-connected";
    if (value === "not_connected") return "connectors-workspace-not-connected";
    if (value === "ambiguous") return "connectors-workspace-ambiguous";
    if (value === "unverified") {
      return authState.authenticated
        ? "connectors-workspace-unverified"
        : "connectors-workspace-sign-in";
    }
    return "connectors-workspace-unverified";
  }

  // connector_status_projection.py keeps the Telegram and Slack workspace rows
  // "unverified" BY DESIGN (no trusted workspace authority exists for them), so
  // when the status check itself fails those two cards keep their by-design
  // preparing copy (connectors-workspace-unverified) on both slots. Every
  // other card keeps the check-failed copy: for the reviewed connectors a
  // failed status read is a real error the retry button addresses, never a
  // state.
  function connectorUnavailableCopyKeys(connectorId) {
    if (connectorId === "connector:telegram:bot@1" || connectorId === "connector:slack:workspace@1") {
      return { support: "connectors-workspace-unverified", workspace: "connectors-workspace-unverified" };
    }
    return { support: "connectors-status-unavailable", workspace: "connectors-workspace-unavailable" };
  }

  // Google Calendar has a second, independent axis: the READ grant activation
  // (#2952). "Google account connected" (the OAuth/workspace axis) must never
  // read as "Calendar read is ready" — they are separate truths. The session
  // state starts "unknown" and is then filled from two bounded sources: the
  // persisted server projection (row.calendar_read_grant_state) and the
  // in-session activation result. The server truth is a projection of the
  // Engine's own grant store — "unavailable" means the check could not be
  // trusted, never that the grant is missing.

  // Pure server-truth → session-state transition. The server projection fills
  // an unset ("unknown") or stale-unavailable session state and can raise it
  // to "active" — that is what makes a fresh page load show the persisted
  // grant instead of "activation needed". It never overwrites an in-session
  // truth ("activating"/"active"/"failed"): the activation response and the
  // user's own retry flow stay authoritative for this session, and a failed
  // status check ("unavailable") never claims the grant is missing.

  function liveConnectorCards() {
    const scope = connectorsScope();
    if (!scope) return [];
    try {
      return Array.from(scope.querySelectorAll("[data-connector-id]"));
    } catch (_) {
      return [];
    }
  }

  function googleDriveConnectButton() {
    const scope = connectorsScope();
    if (!scope) return null;
    try {
      return scope.querySelector(`[data-google-connector-connect="${GOOGLE_DRIVE_CONNECTOR}"]`);
    } catch (_) {
      return null;
    }
  }

  function googleDriveCard() {
    const scope = connectorsScope();
    if (!scope) return null;
    try {
      return scope.querySelector(`[data-connector-id="connector:google:drive@1"]`);
    } catch (_) {
      return null;
    }
  }

  function gmailConnectButton() {
    const scope = connectorsScope();
    if (!scope) return null;
    try {
      return scope.querySelector(`[data-google-connector-connect="${GOOGLE_GMAIL_CONNECTOR}"]`);
    } catch (_) {
      return null;
    }
  }

  /** The whole Drive visibility rule as a pure predicate: an authenticated
   *  session and a canonical ``not_connected`` row. ``unverified``,
   *  ``ambiguous``, ``connected``, a missing row and a signed-out session all
   *  withhold the action, so the browser can never start a connect for a
   *  workspace whose truth it does not hold. */
  function driveConnectOffered(authenticated, workspaceState) {
    return Boolean(authenticated && workspaceState === "not_connected");
  }

  /** Drive has no second axis: connect is the whole action. */
  function syncGoogleDriveConnectButton(row = null) {
    const button = googleDriveConnectButton();
    if (!button) return;
    const workspaceState = row && typeof row.workspace_state === "string" ? row.workspace_state : "";
    const offered = driveConnectOffered(authState.authenticated, workspaceState);
    button.hidden = !offered;
    button.disabled = googleConnectorConnectInFlight;
    if (offered && !googleConnectorConnectInFlight) {
      setConnectorCopy(button, "connectors-connect-drive");
    }
  }

  // #7607: the server says when a connect was started from an address that
  // cannot finish it; that one refusal gets its own line instead of "try again".
  function connectorTicketErrorKey(startDocument, fallbackKey) {
    const code = startDocument && startDocument.error && startDocument.error.code;
    return code === "connector_ticket_origin_not_canonical" ? "connectors-connect-canonical-only" : fallbackKey;
  }

  async function beginGoogleDriveConnect() {
    const button = googleDriveConnectButton();
    if (!button || googleConnectorConnectInFlight) return;
    if (!authState.authenticated) {
      openAuthDialog();
      return;
    }
    googleConnectorConnectInFlight = true;
    button.disabled = true;
    setConnectorCopy(button, "connectors-connecting-drive");
    if (connectorsError) connectorsError.hidden = true;
    let ticketErrorKey = "connectors-connect-drive-error";
    try {
      // Exactly one ticket POST per user attempt. The raw connect ticket is
      // never handed to this scope: the reviewed route performs the single
      // OAuth-edge exchange server-side and answers with the bounded
      // authorization shape only, so no ticket, provider or credential
      // material can reach the DOM, storage, logs or the query string.
      const startResponse = await fetch(GOOGLE_DRIVE_TICKET_ENDPOINT, {
        method: "POST",
        headers: { "Accept": "application/json", "Content-Type": "application/json" },
        body: JSON.stringify({ connector_id: GOOGLE_DRIVE_CONNECTOR, begin_oauth: true }),
        cache: "no-store",
      });
      const startDocument = await startResponse.json().catch(() => null);
      const authorization = startDocument && startDocument.authorization;
      const redirect = startResponse.ok && authorization &&
        authorization.connector_id === GOOGLE_DRIVE_CONNECTOR
        ? reviewedGoogleAuthorizationUrl(authorization.authorization_url)
        : null;
      if (!redirect) ticketErrorKey = connectorTicketErrorKey(startDocument, ticketErrorKey);
      if (!redirect) throw new Error("drive authorization unavailable");
      window.location.assign(redirect);
    } catch (_) {
      // Bounded failure with no automatic retry: only a new explicit user
      // gesture starts another attempt, and this attempt's state is dropped.
      googleConnectorConnectInFlight = false;
      button.disabled = false;
      setConnectorCopy(button, "connectors-connect-drive");
      if (connectorsError) {
        setConnectorCopy(connectorsError, ticketErrorKey);
        connectorsError.hidden = false;
      }
    }
  }

  /** Gmail carries the same rule as Drive: connect is the whole action. */
  function syncGmailConnectButton(row = null) {
    const button = gmailConnectButton();
    if (!button) return;
    const workspaceState = row && typeof row.workspace_state === "string" ? row.workspace_state : "";
    const offered = driveConnectOffered(authState.authenticated, workspaceState);
    button.hidden = !offered;
    button.disabled = googleConnectorConnectInFlight;
    if (offered && !googleConnectorConnectInFlight) {
      setConnectorCopy(button, "connectors-connect-gmail");
    }
  }

  async function beginGmailConnect() {
    const button = gmailConnectButton();
    if (!button || googleConnectorConnectInFlight) return;
    if (!authState.authenticated) {
      openAuthDialog();
      return;
    }
    googleConnectorConnectInFlight = true;
    button.disabled = true;
    setConnectorCopy(button, "connectors-connecting-gmail");
    if (connectorsError) connectorsError.hidden = true;
    let ticketErrorKey = "connectors-connect-drive-error";
    try {
      const startResponse = await fetch(GOOGLE_GMAIL_TICKET_ENDPOINT, {
        method: "POST",
        headers: { "Accept": "application/json", "Content-Type": "application/json" },
        body: JSON.stringify({ connector_id: GOOGLE_GMAIL_CONNECTOR, begin_oauth: true }),
        cache: "no-store",
      });
      const startDocument = await startResponse.json().catch(() => null);
      const authorization = startDocument && startDocument.authorization;
      const redirect = startResponse.ok && authorization &&
        authorization.connector_id === GOOGLE_GMAIL_CONNECTOR
        ? reviewedGoogleAuthorizationUrl(authorization.authorization_url)
        : null;
      if (!redirect) ticketErrorKey = connectorTicketErrorKey(startDocument, ticketErrorKey);
      if (!redirect) throw new Error("gmail authorization unavailable");
      window.location.assign(redirect);
    } catch (_) {
      // Bounded failure with no automatic retry: only a new explicit user
      // gesture starts another attempt, and this attempt's state is dropped.
      googleConnectorConnectInFlight = false;
      button.disabled = false;
      setConnectorCopy(button, "connectors-connect-gmail");
      if (connectorsError) {
        setConnectorCopy(connectorsError, ticketErrorKey);
        connectorsError.hidden = false;
      }
    }
  }

  /** Projects the READ-grant axis onto the Calendar card's own state line.
   *  Only visible while the OAuth/workspace axis is "connected"; every value
   *  is one of the four closed session states, rendered through the bounded
   *  textContent sink. */

  function reviewedGoogleAuthorizationUrl(...a) { return authModule().reviewedGoogleAuthorizationUrl(...a); }

  function setConnectorCardsLoading() {
    liveConnectorCards().forEach((card) => {
      card.dataset.connectorStatus = "loading";
      setConnectorCopy(card.querySelector("[data-connector-support]"), "connectors-status-loading");
      setConnectorCopy(card.querySelector("[data-connector-workspace]"), "connectors-workspace-loading");
    });
    syncGoogleCalendarConnectButton();
    syncGoogleDriveConnectButton();
    syncGmailConnectButton();
  }

  function setConnectorCardsUnavailable() {
    liveConnectorCards().forEach((card) => {
      card.dataset.connectorStatus = "unavailable";
      const keys = connectorUnavailableCopyKeys(card.dataset.connectorId);
      setConnectorCopy(card.querySelector("[data-connector-support]"), keys.support);
      setConnectorCopy(card.querySelector("[data-connector-workspace]"), keys.workspace);
    });
    syncGoogleCalendarConnectButton();
    syncGoogleDriveConnectButton();
    syncGmailConnectButton();
  }

  function renderConnectorStatus(document) {
    if (!document || document.static_support_vs_workspace_state_separated !== true ||
        document.send_write_authorized !== false || !Array.isArray(document.connectors)) {
      throw new Error("connector status unavailable");
    }
    const rows = new Map();
    document.connectors.forEach((row) => {
      if (!row || typeof row.connector_id !== "string" || !CONNECTOR_STATUS_IDS.has(row.connector_id)) return;
      rows.set(row.connector_id, row);
    });
    liveConnectorCards().forEach((card) => {
      const connectorId = card.dataset.connectorId;
      const row = rows.get(connectorId);
      if (!row) {
        card.dataset.connectorStatus = "unavailable";
        setConnectorCopy(card.querySelector("[data-connector-support]"), "connectors-status-unavailable");
        setConnectorCopy(card.querySelector("[data-connector-workspace]"), "connectors-workspace-unavailable");
        return;
      }
      const supportKey = connectorSupportKey(row.read_availability);
      const workspaceKey = connectorWorkspaceKey(row.workspace_state);
      card.dataset.connectorStatus = String(row.workspace_state || "unverified");
      setConnectorCopy(card.querySelector("[data-connector-support]"), supportKey);
      setConnectorCopy(card.querySelector("[data-connector-workspace]"), workspaceKey);
    });
    syncGoogleCalendarConnectButton(rows.get("connector:google:calendar@1") || null);
    syncGoogleDriveConnectButton(rows.get("connector:google:drive@1") || null);
    syncGmailConnectButton(rows.get("connector:google:gmail@1") || null);
  }

  async function loadConnectorStatus() {
    if (!connectorsDialog || connectorStatusInFlight) return;
    connectorStatusInFlight = true;
    if (connectorsLoading) connectorsLoading.hidden = false;
    if (connectorsError) {
      setConnectorCopy(connectorsError, "connectors-error");
      connectorsError.hidden = true;
    }
    if (connectorsRetry) {
      connectorsRetry.hidden = true;
      connectorsRetry.disabled = true;
    }
    setConnectorCardsLoading();
    try {
      // #7368: a front-edge loss (502/503/504) or a network error asks one
      // more time after 0.8s. The checking state persists through the retry,
      // and a second failure keeps the same unavailable answer as before.
      const response = await window.PadiemChatTransport.fetchStatusWithRetry("/api/connectors/status", {
        headers: { "Accept": "application/json" },
        cache: "no-store",
      });
      const data = await response.json().catch(() => null);
      if (!response.ok) throw new Error("connector status unavailable");
      renderConnectorStatus(data);
      if (googleCalendarReadActivationAfterConnectReturn) {
        googleCalendarReadActivationAfterConnectReturn = false;
        const calendarButton = googleCalendarConnectButton();
        if (calendarButton?.dataset.calendarAction === "activate-read") {
          await activateGoogleCalendarRead();
        }
      }
    } catch (_) {
      setConnectorCardsUnavailable();
      if (connectorsError) connectorsError.hidden = false;
      if (connectorsRetry) connectorsRetry.hidden = false;
    } finally {
      connectorStatusInFlight = false;
      if (connectorsLoading) connectorsLoading.hidden = true;
      if (connectorsRetry) connectorsRetry.disabled = false;
    }
  }

  // Standalone Connectors page: the card grid and the live-status block are
  // moved once from #connectorsDialog into #connectorsViewBody. Moving (not
  // cloning) preserves every directly bound listener, and all status queries
  // below scope to the view body first with the dialog as fallback, so the
  // existing fetch/render/connect/retry/OAuth logic is reused byte-for-byte.
  // No endpoint, permission, login or connection state is reset by the move.
  function connectorsScope() {
    try {
      const body = document.getElementById("connectorsViewBody");
      if (body && body.querySelector("[data-connector-id]")) return body;
    } catch (_) {}
    return connectorsDialog;
  }
  let connectorsViewMounted = false;
  function mountConnectorsView() {
    if (connectorsViewMounted) return;
    let body = null;
    let grid = null;
    let status = null;
    try {
      body = document.getElementById("connectorsViewBody");
      grid = connectorsDialog ? connectorsDialog.querySelector(".capability-grid") : null;
      status = document.getElementById("connectorsLiveStatus");
    } catch (_) {
      return;
    }
    if (!body || !grid) return;
    if (status) body.appendChild(status);
    body.appendChild(grid);
    connectorsViewMounted = true;
  }

  function openConnectorsView() {
    mountConnectorsView();
    const view = document.getElementById("connectorsView");
    if (view) view.hidden = false;
    shell.dataset.state = "connectors";
    setNavActive();
    closeSidebar();
    if (connectorsNavButton) connectorsNavButton.setAttribute("aria-expanded", "false");
    void loadConnectorStatus();
  }
  // Kept for existing callers (OAuth return, quick-connect fallback): the
  // Connectors surface is now the standalone page, never a popup.
  function openConnectorsDialog() {
    openConnectorsView();
  }
  function closeConnectorsDialog() {
    if (!connectorsDialog) return;
    if (connectorsDialog.open && typeof connectorsDialog.close === "function") connectorsDialog.close();
    else connectorsDialog.removeAttribute("open");
    if (connectorsNavButton) {
      connectorsNavButton.setAttribute("aria-expanded", "false");
      // Return focus to the sidebar entry that opened it.
      if (typeof connectorsNavButton.focus === "function") connectorsNavButton.focus();
    }
  }
  if (connectorsNavButton) connectorsNavButton.addEventListener("click", openConnectorsView);
  if (connectorsDialogClose) connectorsDialogClose.addEventListener("click", closeConnectorsDialog);
  if (connectorsRetry) connectorsRetry.addEventListener("click", () => void loadConnectorStatus());
  document.addEventListener("padiem:refresh-connector-status", () => void loadConnectorStatus());
  const calendarConnectButton = window.PadiemChatCalendarModule ? googleCalendarConnectButton() : null;
  if (calendarConnectButton) calendarConnectButton.addEventListener("click", () => {
    if (calendarConnectButton.dataset.calendarAction === "activate-read") {
      void activateGoogleCalendarRead();
      return;
    }
    void beginGoogleCalendarConnect();
  });
  // #3289: Drive connect starts only from this explicit user gesture.
  const driveConnectButton = googleDriveConnectButton();
  if (driveConnectButton) driveConnectButton.addEventListener("click", () => {
    void beginGoogleDriveConnect();
  });
  // #7088: Gmail connect starts only from this explicit user gesture.
  const gmailConnectButtonEl = gmailConnectButton();
  if (gmailConnectButtonEl) gmailConnectButtonEl.addEventListener("click", () => {
    void beginGmailConnect();
  });
  document.addEventListener("padiem:drive-quick-connect", () => {
    void (async () => {
      // Existing server-trusted workspace truth, not a synthetic OFF.
      await loadConnectorStatus();
      const offered = googleDriveConnectButton();
      if (offered && !offered.hidden && !offered.disabled) {
        offered.click();
      } else {
        openConnectorsDialog();
      }
    })();
  });
  if (connectorsDialog) {
    connectorsDialog.addEventListener("cancel", (event) => {
      event.preventDefault();
      closeConnectorsDialog();
    });
    connectorsDialog.addEventListener("close", () => connectorsNavButton?.setAttribute("aria-expanded", "false"));
  }

  const connectorReturnSearch = typeof window.location.search === "string" ? window.location.search : "";
  const connectorReturnParts = connectorReturnSearch.replace(/^\?/, "").split("&").filter(Boolean);
  const connectorReturned = connectorReturnParts.some((part) => part === "google_connector=connected");
  if (connectorReturned) {
    googleCalendarReadActivationAfterConnectReturn = true;
    const cleanQuery = connectorReturnParts.filter((part) => !part.startsWith("google_connector=")).join("&");
    const cleanPath = String(window.location.pathname || "/");
    const cleanHash = String(window.location.hash || "");
    window.history.replaceState(null, "", cleanPath + (cleanQuery ? `?${cleanQuery}` : "") + cleanHash);
    openConnectorsDialog();
  }

  if (connectorReturnParts.some(part => part === "claw-github=connected")) {
    const cleanQuery = connectorReturnParts.filter(part => !part.startsWith("claw-github=")).join("&");
    const cleanPath = String(window.location.pathname || "/");
    const cleanHash = String(window.location.hash || "");
    window.history.replaceState(null, "", cleanPath + (cleanQuery ? "?" + cleanQuery : "") + cleanHash);
    openClawWorkspace();
  }

  if (clawNavButton) clawNavButton.addEventListener("click", openClawWorkspace);
  // #4647 Same central workbench for menu entry and Claw natural language.
  window.addEventListener("padiem:meeting-open", () => {
    if (!authState.authenticated) return;
    shell.dataset.state = "meeting";
    setNavActive();
    closeSidebar();
  });
  const clawManualEntryButton = document.getElementById("clawManualEntryButton");
  if (clawManualEntryButton) clawManualEntryButton.addEventListener("click", openClawManual);
  // #4462: background task history stays reachable from the general Claw
  // entry bar (#3531 keeps the workspace canvas hidden in general/manual
  // views, so the entry lives beside the manual-entry control instead).
  // In-conversation run status/results are unchanged.
  if (clawManualForm) {
    const modeChips = clawManualForm.querySelectorAll(".claw-chip[data-claw-action]");
    modeChips.forEach((chip) => {
      chip.addEventListener("click", () => {
        const action = chip.dataset.clawAction;
        if (clawAction && action) clawAction.value = action;
        modeChips.forEach((other) => {
          other.setAttribute("aria-pressed", other === chip ? "true" : "false");
        });
        clawLastAction = action || null;
        input.focus();
      });
    });
    // Keyboard: chips are buttons so Enter/Space already work; ensure roving focus stays visible.
  }
  setNavActive();

  function approvalDecisionErrorMessage(...a) { return conversationModule().approvalDecisionErrorMessage(...a); }


  clawFormModule().wireManualForm();

  // Keep preview/execute hints in sync with locale switches (data-locale-key auto-syncs static text,
  // but status and dynamic card chrome need manual refresh when language toggles).
  window.addEventListener("padiem:localechange", () => {
    // Wait state owns the status region while a long-wait stage is announced:
    // re-render its copy from state so the elapsed value is preserved rather
    // than reset by a language switch.
    if (clawWaitStartedAt && renderClawWait()) applyClawWaitStageCopy();
    else if (clawStatus && !clawStatus.hidden && clawStatus.dataset.localeKey) {
      clawStatus.textContent = clawT(clawStatus.dataset.localeKey);
    }
    // Recovery copy carries runtime values, so it is re-rendered from state
    // instead of being re-resolved from a locale key.
    if (clawRetryBox && !clawRetryBox.hidden) renderClawRetryBox();
    if (clawRetryHint && !clawRetryHint.hidden && clawRetryHint.dataset.localeKey) {
      clawRetryHint.textContent = clawT(clawRetryHint.dataset.localeKey);
    }
    // Re-apply badge text to current card state if visible
    if (clawResultCard && !clawResultCard.hidden && clawResultBadge) {
      const isExecuted = clawResultBadge.dataset.localeKey === "claw-result-badge-run";
      try { clawResultBadge.textContent = window.__padiemLocale.text(isExecuted ? "claw-result-badge-run" : "claw-result-badge"); } catch (_) {}
    }
  });

  setNote(idleNote());
  renderProjectState();
  updateComposer();
  // A guide example arrives as text only: it fills the composer, sends nothing,
  // and leaves no query in the address bar for the next refresh to replay.
  const exampleOnLoad = examplePromptFromLocation();
  if (exampleOnLoad) {
    input.value = exampleOnLoad;
    updateComposer();
    try {
      window.history.replaceState(null, "", window.location.pathname);
    } catch (_) {}
  }
  window.PadiemChatSession.bind({
    clearHistoryUI, clearProjectsUI, resetConversationView, clearAndroidHandoff,
    hasAndroidHandoff: () => Boolean(androidHandoff),
    clearHandoffStorage: () => {
      try { window.sessionStorage.removeItem(ANDROID_HANDOFF_STORAGE_KEY); } catch (_) {}
    },
  });
  window.PadiemClawSession.bind({
    noteApprovalSession: noteClawApprovalSession,
    clearRecovery: clearClawRecovery,
    clearWait: clearClawWait,
  });
  // #5481: a mailed one-time link opens the reset confirm view directly, so
  // the member lands on the "set a new password" step without signing in.
  const resetLinkOnLoad = passwordResetTokenFromLocation();
  if (resetLinkOnLoad) {
    void loadAuthStatus().then(() => openAuthDialog());
  } else {
    void loadAuthStatus();
  }
  resumeAndroidHandoff();
  // Initial state
  setClawAreaState("idle");
  clearClawArtifact();


  clawFormModule().wireExecuteControls();

  function approvedMemoryErrorMessage(...a) { return conversationModule().approvedMemoryErrorMessage(...a); }

  // R5 A2: the approved-memory module owns its declarations (rule (a)) and
  // wires its refresh listener here at the original position (rule (b)).
  const memory = app.provide("memory",
    window.PadiemChatMemoryModule.create(app));
  memory.wireMemoryListeners();

  // Claw recent-run presentation (#2317 owner-scoped run history route).
  // Presentation only: the browser renders what GET /api/claw/runs already
  // exposes to the signed-in owner and never mints its own run/history truth.
  // #4488 Phase A: recent runs are progressive disclosure on the Claw entry.
  const clawRunHistoryDisclosure = document.getElementById("clawRunHistoryDisclosure");
  const clawRunHistoryLoading = document.getElementById("clawRunHistoryLoading");
  const clawRunHistoryError = document.getElementById("clawRunHistoryError");
  const clawRunHistoryList = document.getElementById("clawRunHistoryList");
  const clawRunHistoryEmpty = document.getElementById("clawRunHistoryEmpty");

  let clawRunHistoryInFlight = false;
  // Set when the workspace is left, so the next reveal reads again instead of
  // reusing a list read before the person went elsewhere.
  let clawRunHistoryLeftSurface = false;
  // #3932: server caps owner-scoped history at MAX_CLAW_RUNS=30.
  // Expanding is a read-only, explicit user action, not pagination authority.
  let clawRunHistoryLimit = 10;
  let pendingClawRunFocusId = "";
  let clawRunHistoryVisibilityEpoch = 0;
  const clawRunHistoryPdfControllers = new Set();
  function clearClawRunHistoryPdfPreviews(...a) { return historyModule().clearClawRunHistoryPdfPreviews(...a); }

  function setClawRunHistoryStatus(...a) { return historyModule().setClawRunHistoryStatus(...a); }

  function clawRunHistoryErrorMessage(...a) { return historyModule().clawRunHistoryErrorMessage(...a); }

  // R5 A2: the run-history module owns the runs-read cache, card renderer, and
  // filter/refresh/expand buttons (rule (a)), wired at the original position.
  const runHistory = app.provide("runHistory",
    window.PadiemChatRunHistoryModule.create(app));

  function fetchClawRunHistory(...a) { return historyModule().fetchClawRunHistory(...a); }

  function loadClawRunHistory(...a) { return historyModule().loadClawRunHistory(...a); }

  function syncClawRunHistoryVisibility(...a) { return historyModule().syncClawRunHistoryVisibility(...a); }

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
  else if (window.location.hash === CLAW_ROUTE_HASH) openClawWorkspace();
  else if (window.location.hash === CONNECTORS_ROUTE_HASH) openConnectorsView();
  else if (window.location.hash === ADVANCED_SETTINGS_ROUTE_HASH) openAdvancedSettingsView();
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
