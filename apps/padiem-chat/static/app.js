(() => {
  "use strict";
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
        get clawRunHistory() { return clawRunHistory; },
        get clawRunHistoryDisclosure() { return clawRunHistoryDisclosure; },
        get clawRunHistoryExpand() { return clawRunHistoryExpand; },
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
        get readClawRuns() { return readClawRuns; },
        get mappedUiError() { return mappedUiError; },
        get safeLocalUiMessage() { return safeLocalUiMessage; },
        get failureCodeNote() { return failureCodeNote; },
        get renderClawRunCard() { return renderClawRunCard; },
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
        get syncApprovedMemoryVisibility() { return syncApprovedMemoryVisibility; },
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
        get invalidateClawRunsRead() { return invalidateClawRunsRead; },
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

  // R5 A1: the automation modules own the rule list/read-only catalogue/toggle
  // and the edit+create forms. The declaration block and the top-level listener
  // registrations stay in app.js (R5 B1 moves them); the moved bodies read and
  // write them only through the deps getters/setters below.
  let automationModuleInstance = null;
  function automationModule() {
    if (!automationModuleInstance) {
      automationModuleInstance = window.PadiemChatAutomationModule.create({
        get authState() { return authState; },
        get automationViewMounted() { return automationViewMounted; },
        set automationViewMounted(value) { automationViewMounted = value; },
        get clawAutomation() { return clawAutomation; },
        get clawAutomationEmpty() { return clawAutomationEmpty; },
        get clawAutomationError() { return clawAutomationError; },
        get clawAutomationForbidden() { return clawAutomationForbidden; },
        get clawAutomationInFlightRules() { return clawAutomationInFlightRules; },
        get clawAutomationList() { return clawAutomationList; },
        get clawAutomationLoading() { return clawAutomationLoading; },
        get clawAutomationRetry() { return clawAutomationRetry; },
        get clawAutomationToggleStatus() { return clawAutomationToggleStatus; },
        get clawWorkspace() { return clawWorkspace; },
        get clearClawWait() { return clearClawWait; },
        get closeSidebar() { return closeSidebar; },
        get findRuleToggleButton() { return findRuleToggleButton; },
        get focusRuleToggleAfterReload() { return focusRuleToggleAfterReload; },
        get loadClawAutomationRules() { return loadClawAutomationRules; },
        get mountAutomationView() { return mountAutomationView; },
        get openClawAutomationEdit() { return openClawAutomationEdit; },
        get renderClawAutomationRules() { return renderClawAutomationRules; },
        get resetClawAutomationState() { return resetClawAutomationState; },
        get setClawAutomationError() { return setClawAutomationError; },
        get setClawAutomationForbidden() { return setClawAutomationForbidden; },
        get setClawAutomationLoading() { return setClawAutomationLoading; },
        get setClawAutomationRetryVisible() { return setClawAutomationRetryVisible; },
        get setClawAutomationToggleStatus() { return setClawAutomationToggleStatus; },
        get setNavActive() { return setNavActive; },
        get shell() { return shell; },
        get syncClawRunHistoryVisibility() { return syncClawRunHistoryVisibility; },
        get toggleClawAutomationRule() { return toggleClawAutomationRule; },
        get uiT() { return uiT; },
      });
    }
    return automationModuleInstance;
  }
  let automationFormModuleInstance = null;
  function automationFormModule() {
    if (!automationFormModuleInstance) {
      automationFormModuleInstance = window.PadiemChatAutomationFormModule.create({
        get clawAutomation() { return clawAutomation; },
        get clawAutomationCreate() { return clawAutomationCreate; },
        get clawAutomationCreateCron() { return clawAutomationCreateCron; },
        get clawAutomationCreateCronField() { return clawAutomationCreateCronField; },
        get clawAutomationCreateDaypart() { return clawAutomationCreateDaypart; },
        get clawAutomationCreateDaypartField() { return clawAutomationCreateDaypartField; },
        get clawAutomationCreateExpression() { return clawAutomationCreateExpression; },
        get clawAutomationCreateForm() { return clawAutomationCreateForm; },
        get clawAutomationCreateInFlight() { return clawAutomationCreateInFlight; },
        set clawAutomationCreateInFlight(value) { clawAutomationCreateInFlight = value; },
        get clawAutomationCreateInterval() { return clawAutomationCreateInterval; },
        get clawAutomationCreateIntervalField() { return clawAutomationCreateIntervalField; },
        get clawAutomationCreateKind() { return clawAutomationCreateKind; },
        get clawAutomationCreateName() { return clawAutomationCreateName; },
        get clawAutomationCreateOpen() { return clawAutomationCreateOpen; },
        get clawAutomationCreateOutput() { return clawAutomationCreateOutput; },
        get clawAutomationCreateStatus() { return clawAutomationCreateStatus; },
        get clawAutomationCreateSubmit() { return clawAutomationCreateSubmit; },
        get clawAutomationCreateTarget() { return clawAutomationCreateTarget; },
        get clawAutomationCreateTask() { return clawAutomationCreateTask; },
        get clawAutomationCreateTimezone() { return clawAutomationCreateTimezone; },
        get clawAutomationCreateToggle() { return clawAutomationCreateToggle; },
        get clawAutomationEditCron() { return clawAutomationEditCron; },
        get clawAutomationEditCronField() { return clawAutomationEditCronField; },
        get clawAutomationEditDaypart() { return clawAutomationEditDaypart; },
        get clawAutomationEditDaypartField() { return clawAutomationEditDaypartField; },
        get clawAutomationEditExpression() { return clawAutomationEditExpression; },
        get clawAutomationEditForm() { return clawAutomationEditForm; },
        get clawAutomationEditInFlight() { return clawAutomationEditInFlight; },
        set clawAutomationEditInFlight(value) { clawAutomationEditInFlight = value; },
        get clawAutomationEditInterval() { return clawAutomationEditInterval; },
        get clawAutomationEditIntervalField() { return clawAutomationEditIntervalField; },
        get clawAutomationEditKind() { return clawAutomationEditKind; },
        get clawAutomationEditName() { return clawAutomationEditName; },
        get clawAutomationEditStatus() { return clawAutomationEditStatus; },
        get clawAutomationEditSubmit() { return clawAutomationEditSubmit; },
        get clawAutomationEditTimezone() { return clawAutomationEditTimezone; },
        get clawAutomationEditingRuleId() { return clawAutomationEditingRuleId; },
        set clawAutomationEditingRuleId(value) { clawAutomationEditingRuleId = value; },
        get clawAutomationList() { return clawAutomationList; },
        get closeClawAutomationCreate() { return closeClawAutomationCreate; },
        get closeClawAutomationEdit() { return closeClawAutomationEdit; },
        get findRuleEditButton() { return findRuleEditButton; },
        get loadClawAutomationRules() { return loadClawAutomationRules; },
        get resetClawAutomationCreateForm() { return resetClawAutomationCreateForm; },
        get setClawAutomationCreateStatus() { return setClawAutomationCreateStatus; },
        get setClawAutomationEditStatus() { return setClawAutomationEditStatus; },
        get syncClawAutomationCreateFields() { return syncClawAutomationCreateFields; },
        get syncClawAutomationEditFields() { return syncClawAutomationEditFields; },
        get uiT() { return uiT; },
      });
    }
    return automationFormModuleInstance;
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

  function uiT(key, variables = null) {
    try {
      if (window.__padiemLocale && typeof window.__padiemLocale.text === "function") {
        const value = window.__padiemLocale.text(key, variables);
        if (value && value !== key) return value;
      }
    } catch (_) {}
    return key;
  }
  function attachmentCopy(...a) { return conversationModule().attachmentCopy(...a); }
  function idleNote() {
    return activeProject ? uiT("active-project-note", { name: activeProject.name }) : attachmentCopy().idleNote;
  }
  function setNote(text, state = "normal") {
    runtimeNote.textContent = text;
    runtimeNote.dataset.state = state;
  }
  // #6126: the one legacy-HWP answer the screens show — an ordinary save-as
  // instruction plus the three HWPX steps, never an error state.
  function hwpLegacyGuidance() {
    return uiT("hwp-legacy-guidance") + "\n" + uiT("hwp-legacy-steps");
  }
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
  function formatClockTime(value) {
    const date = value instanceof Date && !Number.isNaN(value.getTime()) ? value : new Date();
    return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
  }

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

  function formatBytes(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
  function extensionOf(name) {
    const lower = String(name || "").toLowerCase();
    const index = lower.lastIndexOf(".");
    return index >= 0 ? lower.slice(index) : "";
  }
  function documentMediaType(file) {
    if (ALLOWED_DOCUMENT_TYPES.has(file.type)) return file.type;
    return DOCUMENT_EXTENSION_TYPES.get(extensionOf(file.name)) || null;
  }
  function clearAttachment(...a) { return conversationModule().clearAttachment(...a); }
  function attachmentCountLimit(...a) { return conversationModule().attachmentCountLimit(...a); }
  function attachmentTrayNote(...a) { return conversationModule().attachmentTrayNote(...a); }
  function removeAttachmentItem(...a) { return conversationModule().removeAttachmentItem(...a); }
  function renderAttachmentChips(...a) { return conversationModule().renderAttachmentChips(...a); }
  function readAsText(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.addEventListener("load", () => resolve(reader.result), { once: true });
      reader.addEventListener("error", () => reject(new Error(uiT("document-read-failed"))), { once: true });
      reader.readAsText(file, "UTF-8");
    });
  }
  async function readDocumentFile(file) {
    if (extensionOf(file.name) === ".hwp") {
      // #6126 backstop: selection-time callers refuse an OLE2 .hwp by its own
      // bytes before reaching here; this guard keeps the same one code and
      // wording for any future caller that skips the sniff.
      const error = new Error(uiT("hwp-legacy-guidance"));
      error.uiMessageSafe = true;
      error.code = "legacy_hwp_unsupported";
      throw error;
    }
    const mediaType = documentMediaType(file);
    if (!mediaType) throw new Error(attachmentCopy().unsupportedFormat);
    if (file.size < 1) throw new Error(uiT("empty-document"));
    const raw = await readAsText(file);
    if (typeof raw !== "string") throw new Error(uiT("document-read-failed"));
    const text = raw.replace(/^\uFEFF/, "").replace(/\r\n/g, "\n").replace(/\r/g, "\n");
    if (!text.trim()) throw new Error(uiT("empty-document"));
    if (text.includes("\u0000")) throw new Error(uiT("binary-document"));
    return { type: "document", name: file.name || "document.txt", mediaType, text, byteSize: file.size };
  }
  async function selectImage(file) {
    if (!ALLOWED_IMAGE_TYPES.has(file.type)) throw new Error(attachmentCopy().unsupportedFormat);
    if (file.size < 1) throw new Error(uiT("image-data-empty"));
    return { type: "image", name: file.name || "image", mediaType: file.type, file, byteSize: file.size, previewUrl: URL.createObjectURL(file) };
  }
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
    projectsSection.hidden = true;
    projectsEmpty.hidden = true;
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
  function mappedUiError(message, data) {
    const error = new Error(message);
    error.uiMessageSafe = true;
    const code = data?.error?.code;
    if (typeof code === "string" && /^[a-z][a-z0-9_]{0,63}$/.test(code)) error.code = code;
    return error;
  }
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

  function syncAuthDialogMethods(...a) { return authModule().syncAuthDialogMethods(...a); }

  function openAuthDialog(...a) { return authModule().openAuthDialog(...a); }

  function isAndroidWebView() {
    if (typeof navigator === "undefined") return false;
    const userAgent = navigator.userAgent || "";
    return /Android/i.test(userAgent) && /\bwv\b/i.test(userAgent);
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

  function stopAndroidHandoffPolling() {
    if (androidHandoffTimer !== null) {
      window.clearInterval(androidHandoffTimer);
      androidHandoffTimer = null;
    }
  }

  function clearAndroidHandoff() {
    stopAndroidHandoffPolling();
    androidHandoffClaiming = false;
    androidHandoff = null;
    storeAndroidHandoff();
    renderAndroidHandoff();
    setAuthFormError(androidHandoffError);
  }

  function androidHandoffPhaseKey(phase) {
    switch (phase) {
      case "waiting": return "auth-android-waiting";
      case "confirm": return "auth-android-confirm";
      case "claiming": return "auth-android-claiming";
      case "expired": return "auth-android-expired";
      case "error": return "auth-android-error";
      default: return "auth-android-code-help";
    }
  }

  function renderAndroidHandoff() {
    if (!androidHandoffPanel) return;
    if (!androidHandoff) {
      androidHandoffPanel.hidden = true;
      return;
    }
    androidHandoffPanel.hidden = false;
    if (androidHandoffCode) androidHandoffCode.textContent = androidHandoff.userCode;
    if (androidHandoffNote) {
      const key = androidHandoffPhaseKey(androidHandoff.phase);
      androidHandoffNote.dataset.localeKey = key;
      androidHandoffNote.textContent = uiT(key);
    }
    const busy = androidHandoff.phase === "claiming";
    // The external browser is only useful while the Google sign-in itself
    // is still pending. Once the profile is bound the user only has to
    // enter the code, and re-opening Google would repeat that
    // procedure for nothing.
    const awaitingLogin = androidHandoff.phase === "waiting";
    if (androidHandoffOpen) {
      androidHandoffOpen.hidden = busy || !awaitingLogin;
      androidHandoffOpen.disabled = busy || !awaitingLogin;
    }
    if (androidHandoffCopy) {
      androidHandoffCopy.hidden = busy;
      androidHandoffCopy.disabled = busy;
    }
    if (androidHandoffCopied) {
      androidHandoffCopied.hidden = true;
    }
    if (androidHandoffCancel) {
      androidHandoffCancel.hidden = busy;
      androidHandoffCancel.disabled = busy;
    }
  }

  async function claimAndroidHandoff(current) {
    if (!current || androidHandoffClaiming || androidHandoff !== current) return;
    androidHandoffClaiming = true;
    current.phase = "claiming";
    storeAndroidHandoff();
    renderAndroidHandoff();
    let response;
    try {
      response = await fetch(`/auth/android/handoff/${encodeURIComponent(current.handoffId)}/claim`, {
        method: "POST",
        headers: {
          "Accept": "application/json",
          "X-Padiem-Handoff-Secret": current.claimSecret,
        },
        cache: "no-store",
      });
    } catch (_) {
      current.phase = "waiting";
      storeAndroidHandoff();
      renderAndroidHandoff();
      androidHandoffClaiming = false;
      return;
    }
    if (response.ok) {
      await loadAuthStatus();
      if (authState.authenticated) {
        clearAndroidHandoff();
        closeAuthDialog();
      } else {
        current.phase = "error";
        storeAndroidHandoff();
        renderAndroidHandoff();
      }
      androidHandoffClaiming = false;
      return;
    }
    if (response.status === 410 || response.status === 404) {
      current.phase = "expired";
      stopAndroidHandoffPolling();
    } else if (response.status === 409) {
      await loadAuthStatus();
      if (authState.authenticated) {
        clearAndroidHandoff();
      } else {
        current.phase = "error";
        stopAndroidHandoffPolling();
      }
    } else {
      current.phase = "error";
      stopAndroidHandoffPolling();
    }
    storeAndroidHandoff();
    renderAndroidHandoff();
    androidHandoffClaiming = false;
  }

  async function pollAndroidHandoff() {
    const current = androidHandoff;
    if (!current || androidHandoffClaiming) return;
    if (Date.now() >= current.expiresAt) {
      current.phase = "expired";
      stopAndroidHandoffPolling();
      storeAndroidHandoff();
      renderAndroidHandoff();
      return;
    }
    let response;
    try {
      response = await fetch(`/auth/android/handoff/${encodeURIComponent(current.handoffId)}`, {
        headers: {
          "Accept": "application/json",
          "X-Padiem-Handoff-Secret": current.claimSecret,
        },
        cache: "no-store",
      });
    } catch (_) {
      return; // transient; the next tick retries while the page is alive
    }
    if (response.status === 404) {
      current.phase = "error";
      stopAndroidHandoffPolling();
      storeAndroidHandoff();
      renderAndroidHandoff();
      return;
    }
    if (!response.ok) return;
    const data = await response.json().catch(() => null);
    if (!data || typeof data.status !== "string") return;
    if (data.status === "ready") {
      await claimAndroidHandoff(current);
      return;
    }
    if (data.status === "claimed") {
      await loadAuthStatus();
      if (authState.authenticated) clearAndroidHandoff();
      return;
    }
    if (data.status === "expired" || data.status === "cancelled") {
      current.phase = "expired";
      stopAndroidHandoffPolling();
      storeAndroidHandoff();
      renderAndroidHandoff();
      return;
    }
    current.phase = data.status === "awaiting_confirmation" ? "confirm" : "waiting";
    storeAndroidHandoff();
    renderAndroidHandoff();
  }

  function startAndroidHandoffPolling() {
    stopAndroidHandoffPolling();
    if (!androidHandoff || androidHandoff.phase === "expired" || androidHandoff.phase === "error") return;
    androidHandoffTimer = window.setInterval(() => { pollAndroidHandoff(); }, ANDROID_HANDOFF_POLL_MS);
  }

  async function startAndroidHandoff() {
    if (androidHandoffStarting) return;
    androidHandoffStarting = true;
    setAuthFormError(androidHandoffError);
    try {
      const response = await fetch("/auth/android/handoff", {
        method: "POST",
        headers: { "Accept": "application/json" },
        cache: "no-store",
      });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data ||
          typeof data.handoff_id !== "string" ||
          typeof data.claim_secret !== "string" ||
          typeof data.user_code !== "string" ||
          typeof data.authorization_url !== "string") {
        throw new Error(uiT("auth-android-error"));
      }
      const expiresIn = Number.isFinite(data.expires_in) ? data.expires_in : 600;
      androidHandoff = {
        handoffId: data.handoff_id,
        claimSecret: data.claim_secret,
        userCode: data.user_code,
        authorizationUrl: data.authorization_url,
        expiresAt: Date.now() + Math.max(30, expiresIn - 5) * 1000,
        phase: "waiting",
      };
      storeAndroidHandoff();
      renderAndroidHandoff();
      startAndroidHandoffPolling();
      window.location.assign(androidHandoff.authorizationUrl);
    } catch (error) {
      setAuthFormError(
        androidHandoffError,
        error instanceof Error && error.message ? error.message : uiT("auth-android-error")
      );
    } finally {
      androidHandoffStarting = false;
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

  // The first screen reads /api/claw/runs twice: the sidebar needs the
  // run -> conversation mapping (limit 30) and Claw's history needs the run
  // cards (limit 10). The wider answer already contains the narrower one, so
  // one short-lived in-memory read answers both. It is keyed to the auth
  // generation and never stored outside memory; the window is short enough
  // that a run created just after it is seen on the next read.
  const CLAW_RUNS_READ_WINDOW_MS = 1500;
  const emptyClawRunsRead = () => ({
    at: 0, epoch: -1, limit: 0, response: null, data: null, inFlight: null, inFlightLimit: 0,
  });
  let clawRunsRead = emptyClawRunsRead();

  // A write that changes a run's status makes every answer in the window
  // stale, so the next read asks the server again.
  function invalidateClawRunsRead() {
    clawRunsRead = emptyClawRunsRead();
  }

  function readClawRuns(limit, epoch, options) {
    const force = Boolean(options && options.force === true);
    const now = Date.now();
    // An explicit refresh asks the server. A read already open still answers
    // it, so two rapid clicks stay one request.
    if (!force && clawRunsRead.epoch === epoch && clawRunsRead.data
        && clawRunsRead.limit >= limit
        && now - clawRunsRead.at < CLAW_RUNS_READ_WINDOW_MS) {
      return Promise.resolve({ response: clawRunsRead.response, data: clawRunsRead.data });
    }
    if (clawRunsRead.inFlight && clawRunsRead.epoch === epoch
        && clawRunsRead.inFlightLimit >= limit) {
      return clawRunsRead.inFlight;
    }
    const run = (async () => {
      const response = await fetch(`/api/claw/runs?limit=${limit}`, {
        headers: { "Accept": "application/json" }, cache: "no-store",
      });
      const data = await response.json().catch(() => null);
      if (response.ok && data && data.ok === true && Array.isArray(data.runs)) {
        clawRunsRead = { at: Date.now(), epoch, limit, response, data, inFlight: null, inFlightLimit: 0 };
      }
      return { response, data };
    })();
    clawRunsRead.epoch = epoch;
    clawRunsRead.inFlight = run;
    clawRunsRead.inFlightLimit = limit;
    run.finally(() => {
      if (clawRunsRead.inFlight === run) {
        clawRunsRead.inFlight = null;
        clawRunsRead.inFlightLimit = 0;
      }
    }).catch(() => {});
    return run;
  }

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
      syncApprovedMemoryVisibility();
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
  // The PC lane carries no live P01 stage, so its status chip follows the
  // run's own observed status. The wording is the existing stage vocabulary,
  // and any status shown here is settled by the run's terminal outcome.
  function showPcRuntimeStatus(article, kind) {
    const text = window.PadiemClawRunEventProjection?.label?.(
      kind, document.documentElement.lang
    );
    if (!text) return false;
    window.PadiemChatLifecycle?.applyRuntimeLabel?.(article, text, "status");
    return true;
  }
  async function waitForAcceptedPcRun(article, handle, outboundMessages, signal, product) {
    const { run_id: runId, conversation_id: conversationId } = handle;
    const owner = authState.user;
    if (!runId || !conversationId) return;
    // Chat/Claw separation: the pending run belongs to the product that submitted it, so
    // the guard compares that product's own conversation id.
    for (;;) {
      if (signal.aborted || !article.isConnected || authState.authenticated !== true
          || authState.user !== owner
          || conversationState.getConversationId?.(product) !== conversationId) return;
      await new Promise((resolve) => window.setTimeout(resolve, 2000));
      if (signal.aborted || !article.isConnected || authState.user !== owner
          || conversationState.getConversationId?.(product) !== conversationId) return;
      const response = await fetch(
        "/api/claw/runs/" + encodeURIComponent(runId) + "/pending-result",
        { headers: { Accept: "application/json" }, cache: "no-store", signal }
      );
      if (!response.ok) return;
      const data = await response.json();
      const result = data?.result;
      if (!result || result.run_id !== runId || result.conversation_id !== conversationId) return;
      if (authState.user !== owner || conversationState.getConversationId?.(product) !== conversationId
          || !article.isConnected || signal.aborted) return;
      if (result.status === "pending" || result.status === "running") {
        // A server-observed "running" is a real fact: the Engine reached a PC
        // step for this run. "pending" adds nothing over the preparing chip.
        if (result.status === "running") {
          // A running turn shows its status on the card, which owns that
          // surface, so the observed step is carried as the card's own hint.
          window.PadiemChatLifecycle?.setTaskHint?.(article, "tool");
          showPcRuntimeStatus(article, "tool_started");
        }
        continue;
      }
      if (result.status !== "completed" || typeof result.answer !== "string") {
        window.PadiemChatLifecycle?.setTaskHint?.(article, null);
        if (result.reason === "pc_read_failed") {
          showPcRuntimeStatus(article, "pc_read_failed");
        } else {
          showPcRuntimeStatus(article, "run_failed");
        }
        PadiemChatLifecycle.set(article, MESSAGE_LIFECYCLE.FAILED);
        return;
      }
      // #5015: only a verified PC command result may replace this article as
      // the run's completed PC result. A model reply is not a PC execution:
      // the model's own answer stays in place, and it is never presented as a
      // completed PC run.
      if (result.answer_source !== "pc_command_result") {
        if (result.answer_source === "model_reply") {
          // A model reply is not a completed PC execution, so a tool-running
          // status observed while waiting is released rather than confirmed.
          window.PadiemChatLifecycle?.setTaskHint?.(article, null);
          window.PadiemChatLifecycle?.applyRuntimeLabel?.(article, "", "status");
          PadiemChatLifecycle.set(article, MESSAGE_LIFECYCLE.COMPLETED);
        }
        return;
      }
      if (resolvedPcRuns.has(runId)) return;
      resolvedPcRuns.add(runId);
      const content = article.querySelector(".assistant-content");
      content.replaceChildren();
      window.PadiemChatPcScopeNotice?.render?.(content, result.scope_notice);
      const paragraph = document.createElement("p");
      paragraph.textContent = result.answer;
      content.appendChild(paragraph);
      // The durable run answered: the preparing chip is released, and a
      // tool-running status shown while waiting settles on this run's real
      // completion instead of being left stale.
      window.PadiemChatLifecycle?.setTaskHint?.(article, null);
      window.PadiemChatLifecycle?.releasePreparingRuntimeLabel?.(article);
      showPcRuntimeStatus(article, "run_completed");
      conversationState.setProduct?.(product);
      conversationState.commitAssistant(outboundMessages, result.answer);
      conversationState.setProduct?.(conversationProduct);
      PadiemChatLifecycle.set(article, MESSAGE_LIFECYCLE.COMPLETED);
      if (authState.authenticated) loadRecentConversations();
      return;
    }
  }

  const pcResultRecovery = window.PadiemChatPcRecovery?.create?.({
    fetchImpl: window.fetch.bind(window),
  }) || null;

  // #5895: a PC turn keeps running on the server after this tab goes away, and
  // the owner's run history already names unfinished runs (#3139 reconciles a
  // finished result back into the conversation that started it). Reopening that
  // conversation continues the same "still working" display, with the elapsed
  // time the server's own run row carries, and the stored answer lands in the
  // thread through the existing restore path. Nothing is submitted from here,
  // and no attempt count or deadline is chosen here.
  function pcWaitElapsed(createdAt) {
    const started = Date.parse(createdAt);
    if (!Number.isFinite(started)) return null;
    const clock = window.PadiemChatLifecycle?.elapsedClockText;
    if (typeof clock !== "function") return null;
    return clock(Math.max(0, Date.now() - started));
  }

  async function findUnfinishedPcRun(conversationId) {
    let runs = [];
    try {
      const response = await fetch("/api/claw/runs", {
        headers: { "Accept": "application/json" }, cache: "no-store",
      });
      const data = await response.json().catch(() => null);
      if (response.ok && data?.ok === true && Array.isArray(data.runs)) runs = data.runs;
    } catch (_) {
      // A failed read adds no knowledge: the run is never replayed from here.
      return null;
    }
    return runs.find((run) => run
      && window.PadiemChatPcRecovery?.validRunId?.(run.run_id) === true
      && (run.status === "pending" || run.status === "running")
      && run.session?.conversation_id === conversationId) || null;
  }

  async function resumeUnfinishedPcRun(conversationId) {
    if (!conversationId || !pcResultRecovery) return;
    const unfinished = await findUnfinishedPcRun(conversationId);
    if (!unfinished || resolvedPcRuns.has(unfinished.run_id)) return;
    const showWait = () => {
      const elapsed = pcWaitElapsed(unfinished.created_at);
      setNote(elapsed
        ? uiT("pc-elapsed-note", { elapsed })
        : uiT("pc-processing-note"), "status");
    };
    showWait();
    let result;
    try {
      result = await pcResultRecovery.waitForResult({
        runId: unfinished.run_id, conversationId, onPending: showWait,
      });
    } catch (_) {
      // The read was cancelled or the tab moved on; the run keeps running.
      return;
    }
    if (result.kind === "pending") return;
    // This tab will not read that run again. A completed answer lands in the
    // thread; any other verdict only stops this screen from claiming that work
    // is still happening, because the client cannot see its outcome and is not
    // the one that decides what a finished PC run said.
    resolvedPcRuns.add(unfinished.run_id);
    setNote(idleNote());
    if (result.kind === "completed" && result.conversationId === conversationId) {
      await openSavedConversation(conversationId);
    }
  }

  function renderStoredPcAnswer(article, result, outboundMessages, contextSnapshot) {
    const content = article.querySelector(".assistant-content");
    if (!content) return false;
    const product = contextSnapshot.product || conversationProduct;
    content.replaceChildren();
    // The recovery GET carries the same pinned notice as the live POST.
    window.PadiemChatPcScopeNotice?.render?.(content, result.scopeNotice);
    const paragraph = document.createElement("p");
    paragraph.textContent = result.answer;
    content.appendChild(paragraph);
    window.PadiemChatLifecycle?.releasePreparingRuntimeLabel?.(article);
    // The preparing release deliberately keeps a chip that already carries a
    // real status, and the PC wait paints one for the step it observed. A
    // recovered answer is that run's outcome, so the running wording is
    // released here too; it must not stay on a turn that has already answered.
    window.PadiemChatLifecycle?.applyRuntimeLabel?.(article, "", "status");
    conversationState.setProduct?.(product);
    if (result.conversationId) conversationState.setConversationId(result.conversationId, product);
    conversationState.commitAssistant(outboundMessages, result.answer);
    conversationState.setProduct?.(conversationProduct);
    PadiemChatLifecycle.set(article, MESSAGE_LIFECYCLE.COMPLETED);
    if (authState.authenticated) loadRecentConversations();
    article.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
    return true;
  }

  // A long PC turn can outlive the browser connection. The server may already
  // have persisted the canonical answer, so recover it with the owner-scoped
  // run GET. This path never submits the PC turn again.
  async function recoverStoredPcResult(article, contextSnapshot, outboundMessages, skill, signal) {
    const runId = contextSnapshot?.pcRunId;
    if (!runId || !pcResultRecovery || resolvedPcRuns.has(runId)) return false;
    let first;
    try {
      first = await pcResultRecovery.recoverOnce({
        runId,
        conversationId: contextSnapshot.conversationId,
        signal,
      });
    } catch (error) {
      if (error && error.name === "AbortError") throw error;
      return false;
    }
    if (first.kind === "duplicate") return true;
    if (first.kind === "completed") {
      resolvedPcRuns.add(runId);
      return renderStoredPcAnswer(article, first, outboundMessages, contextSnapshot);
    }
    if (first.kind !== "pending") {
      // A 404 means the server has no such result. Forget this run here and
      // now, so a retry over the same handle skips the check and renders its
      // own failure instead of reading a gone run again.
      if (first.gone === true) resolvedPcRuns.add(runId);
      return false;
    }
    if (first.conversationId) {
      conversationState.setConversationId(first.conversationId, contextSnapshot.product);
    }
    PadiemChatLifecycle.set(article, MESSAGE_LIFECYCLE.STREAMING);
    void pcResultRecovery.waitForResult({
      runId,
      conversationId: first.conversationId,
      signal,
    }).then((result) => {
      if (result.kind === "completed") {
        if (!resolvedPcRuns.has(runId)) {
          resolvedPcRuns.add(runId);
          renderStoredPcAnswer(article, result, outboundMessages, contextSnapshot);
        }
        return;
      }
      if (result.kind === "pending") {
        // #5895: an unfinished run is not a failed run. Say what is actually
        // true — still processing, and the stored answer lands in this
        // conversation — instead of a failure the owner cannot act on.
        PadiemChatLifecycle.set(article, MESSAGE_LIFECYCLE.STREAMING);
        window.PadiemChatLifecycle?.applyRuntimeLabel?.(article, uiT("pc-processing-note"), "status");
        return;
      }
      if (result.gone === true) resolvedPcRuns.add(runId);
      if (article.isConnected && !signal.aborted) {
        renderStreamError(article, uiT("stream-incomplete"), outboundMessages, skill, contextSnapshot, false);
      }
    }).catch((error) => {
      if (error && error.name === "AbortError") return;
      if (article.isConnected && !signal.aborted) {
        PadiemChatLifecycle.set(article, MESSAGE_LIFECYCLE.FAILED);
      }
    });
    return true;
  }

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
  if (androidHandoffOpen) {
    androidHandoffOpen.addEventListener("click", () => {
      if (!androidHandoff) return;
      window.location.assign(androidHandoff.authorizationUrl);
    });
  }
  if (androidHandoffCopy) {
    androidHandoffCopy.addEventListener("click", async () => {
      if (!androidHandoff) return;
      const code = androidHandoff.userCode || "";
      if (!code) return;
      let copied = false;
      try {
        if (navigator.clipboard && window.isSecureContext) {
          await navigator.clipboard.writeText(code);
          copied = true;
        }
      } catch (error) {
        copied = false;
      }
      if (!copied && androidHandoffCode) {
        // Fall back to selecting the code so it can still be copied.
        try {
          const range = document.createRange();
          range.selectNodeContents(androidHandoffCode);
          const selection = window.getSelection();
          if (selection) {
            selection.removeAllRanges();
            selection.addRange(range);
          }
        } catch (error) {}
      }
      if (androidHandoffCopied) {
        androidHandoffCopied.hidden = false;
      }
    });
  }
  if (androidHandoffCancel) {
    androidHandoffCancel.addEventListener("click", () => { clearAndroidHandoff(); });
  }
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && androidHandoff) {
      pollAndroidHandoff();
    }
  });
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
    // #3237: canonical automation rule catalogue. #3257 adds the first Create
  // surface: the browser submits only the seven product fields, while rule id,
  // owner provenance, workspace/subject and the execution target (repository +
  // exact revision) are minted or derived server-side. Editing, deleting,
  // enabling/disabling and run-now remain out of scope.
  const automationNavButton = document.getElementById("automationNavButton");
  const clawAutomation = document.getElementById("clawAutomation");
  const clawAutomationLoading = document.getElementById("clawAutomationLoading");
  const clawAutomationError = document.getElementById("clawAutomationError");
  const clawAutomationForbidden = document.getElementById("clawAutomationForbidden");
  const clawAutomationEmpty = document.getElementById("clawAutomationEmpty");
  const clawAutomationList = document.getElementById("clawAutomationList");
  const clawAutomationRetry = document.getElementById("clawAutomationRetry");
  const clawAutomationCreate = document.getElementById("clawAutomationCreate");
  const clawAutomationCreateToggle = document.getElementById("clawAutomationCreateToggle");
  const clawAutomationCreateOpen = document.getElementById("clawAutomationCreateOpen");
  const clawAutomationCreateForm = document.getElementById("clawAutomationCreateForm");
  const clawAutomationCreateName = document.getElementById("clawAutomationCreateName");
  const clawAutomationCreateTask = document.getElementById("clawAutomationCreateTask");
  const clawAutomationCreateKind = document.getElementById("clawAutomationCreateKind");
  const clawAutomationCreateDaypartField = document.getElementById("clawAutomationCreateDaypartField");
  const clawAutomationCreateDaypart = document.getElementById("clawAutomationCreateDaypart");
  const clawAutomationCreateIntervalField = document.getElementById("clawAutomationCreateIntervalField");
  const clawAutomationCreateInterval = document.getElementById("clawAutomationCreateInterval");
  const clawAutomationCreateCronField = document.getElementById("clawAutomationCreateCronField");
  const clawAutomationCreateCron = document.getElementById("clawAutomationCreateCron");
  const clawAutomationCreateTimezone = document.getElementById("clawAutomationCreateTimezone");
  const clawAutomationCreateTarget = document.getElementById("clawAutomationCreateTarget");
  const clawAutomationCreateOutput = document.getElementById("clawAutomationCreateOutput");
  const clawAutomationCreateStatus = document.getElementById("clawAutomationCreateStatus");
  const clawAutomationCreateSubmit = document.getElementById("clawAutomationCreateSubmit");
  const clawAutomationCreateCancel = document.getElementById("clawAutomationCreateCancel");
  // #3262: enable/disable toggle state for one canonical rule.
  const clawAutomationToggleStatus = document.getElementById("clawAutomationToggleStatus");
  const clawAutomationInFlightRules = new Set();
  // #3270: bounded Edit (name + schedule) on a canonical, execution-ready rule.
  const clawAutomationEditForm = document.getElementById("clawAutomationEditForm");
  const clawAutomationEditName = document.getElementById("clawAutomationEditName");
  const clawAutomationEditKind = document.getElementById("clawAutomationEditKind");
  const clawAutomationEditDaypartField = document.getElementById("clawAutomationEditDaypartField");
  const clawAutomationEditDaypart = document.getElementById("clawAutomationEditDaypart");
  const clawAutomationEditIntervalField = document.getElementById("clawAutomationEditIntervalField");
  const clawAutomationEditInterval = document.getElementById("clawAutomationEditInterval");
  const clawAutomationEditCronField = document.getElementById("clawAutomationEditCronField");
  const clawAutomationEditCron = document.getElementById("clawAutomationEditCron");
  const clawAutomationEditTimezone = document.getElementById("clawAutomationEditTimezone");
  const clawAutomationEditStatus = document.getElementById("clawAutomationEditStatus");
  const clawAutomationEditSubmit = document.getElementById("clawAutomationEditSubmit");
  const clawAutomationEditCancel = document.getElementById("clawAutomationEditCancel");
  let clawAutomationEditingRuleId = null;
  let clawAutomationEditInFlight = false;
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

  function clawT(key, variables = null) {
    try {
      if (window.__padiemLocale && typeof window.__padiemLocale.text === "function") {
        const v = window.__padiemLocale.text(key, variables);
        if (v && v !== key) return v;
      }
    } catch (_) {}
    if (!variables || typeof variables !== "object") return clawFallbackCopy[key] || "Unable to update this Claw status. Please try again.";
    const template = clawFallbackCopy[key] || "Unable to update this Claw status. Please try again.";
    return Object.keys(variables).reduce((out, name) => out.split(`{${name}}`).join(String(variables[name])), template);
  }

  function localeOr(key, fallback) {
    try {
      if (window.__padiemLocale && typeof window.__padiemLocale.text === "function") {
        const value = window.__padiemLocale.text(key);
        if (value && value !== key) return value;
      }
    } catch (_) {}
    return fallback;
  }

  function syncComposerForClaw(isClaw) {
    if (!input) return;
    if (isClaw) shell.dataset.clawTier = selectedProductTier();
    // #3531: the business-request prompt belongs to the explicit manual
    // workflow view only. The general Claw view shares the generic prompt
    // so placeholder parity with Chat Home holds.
    const manualView = isClaw && clawWorkspace && clawWorkspace.dataset.view === "manual";
    if (manualView) {
      input.placeholder = localeOr("claw-request-placeholder", "Paste a business request you received by chat, SMS, or email.");
      input.setAttribute("aria-describedby", "clawStatus");
      // Executable Claw task authority is validated by the server.
      // No separate pilot-era 4,000-character browser ceiling.
    } else {
      // #7166: the general Claw view gets its own one-line placeholder so the
      // shared composer says what Claw does instead of repeating Chat's.
      input.placeholder = isClaw
        ? localeOr("claw-input-placeholder", "What can I do? e.g. tidy files")
        : localeOr("input", "Ask anything");
      input.removeAttribute("aria-describedby");
      input.removeAttribute("aria-invalid");
      // General Claw and Chat accept provider-native prompts. The distinct
      // manual executable tasks keep their separate tool authorization and bounds.
      input.removeAttribute("maxlength");
    }
  }

  function setClawStatus(message, state, localeKey) {
    if (!clawStatus) return;
    if (!message) {
      clawStatus.hidden = true;
      clawStatus.textContent = "";
      clawStatus.removeAttribute("data-state");
      clawStatus.classList?.remove?.("padiem-activity-sweep");
      input.removeAttribute("aria-invalid");
      return;
    }
    clawStatus.hidden = false;
    clawStatus.textContent = message;
    if (state) clawStatus.dataset.state = state;
    else clawStatus.removeAttribute("data-state");
    // #5453: the sweep only rides a state the run is really in.
    clawStatus.classList?.toggle?.("padiem-activity-sweep", state === "running");
    if (localeKey) clawStatus.dataset.localeKey = localeKey;
    else delete clawStatus.dataset.localeKey;
    if (state === "error") input.setAttribute("aria-invalid", "true");
    else input.removeAttribute("aria-invalid");
  }

  function setClawAreaState(state) {
    if (clawResultArea) clawResultArea.dataset.clawState = state;
  }

  function setClawButtonsBusy(busy) {
    clawInFlight = busy;
    const busyVal = busy ? "true" : "false";
    if (clawGenerateBtn) {
      clawGenerateBtn.disabled = busy;
      clawGenerateBtn.setAttribute("aria-busy", busyVal);
      clawGenerateBtn.setAttribute("aria-disabled", String(busy));
    }
    if (clawExecuteButton) {
      // A running pre-dispatch cooldown, and an ambiguous outcome whose dispatch
      // cannot be ruled out, both block the one manual-execute entry point. The
      // draft/preview button and the chat lane stay available: they are separate
      // requests with their own server-side bounds.
      const blocked = busy || clawRetryRemaining() > 0 || clawCurrentDispatchIsUncertain();
      clawExecuteButton.disabled = blocked;
      clawExecuteButton.setAttribute("aria-busy", busyVal);
      clawExecuteButton.setAttribute("aria-disabled", String(blocked));
    }
  }

  // ── Pre-dispatch execute recovery (#2760) ───────────────────────────────
  //
  // Dispatch certainty decides retryability. The server-side UsageGate runs
  // BEFORE P01/Engine dispatch, so a 429 that carries a bounded numeric
  // Retry-After is a known pre-dispatch denial: the browser may offer an
  // explicit, user-pressed retry once that cooldown expires. Failures where a
  // dispatch may already have happened (browser network error, the engine
  // execution-failure family) are ambiguous, so they get a "check Recent runs
  // first" hint and never a retry affordance.
  //
  // Retry target: the CURRENT VISIBLE FORM, re-read at click time. No hidden
  // payload snapshot is stored, so a stale request cannot be replayed. Nothing
  // in this block submits on a timer; the ticker only re-renders copy and
  // control state. No auto-retry, no provider retry, no server policy change.
  // The bound lives on the SERVER, not here (#5882 A-15). app/usage_gate.py is
  // the only producer of Retry-After on these routes and it emits a fixed
  // integer — 60s for the minute bucket — while quota_exhausted and
  // service_limit_reached carry no header at all (claw_routes.py:270 guards the
  // emission). A second 900s client re-clamp could therefore never bind; it only
  // risked disagreeing with the server and blocking this form for a ceiling the
  // server is not enforcing. The parsed seconds are used exactly as sent, and
  // the closed parse below is what fails closed on malformed/negative/HTTP-date
  // values instead of a ceiling.

  function clawRetryRemaining() {
    return clawRetrySeconds > 0 ? clawRetrySeconds : 0;
  }

  // The manual-execute lane's duplicate check compares WIRE CONTENT, so the
  // request shape is assembled in exactly one place and reused by both the
  // dispatch and the comparison. Canonical conversation reuse (#2916): forward
  // only the exact handle this page already owns; the browser never mints one.
  // The model ID field is deliberately absent — /api/claw/manual-intake/execute
  // does not read it (it selects the conversation lane only), so changing it
  // cannot make the next run a different request.
  function clawVisibleExecutePayload() {
    const body = (input.value || "").trim();
    const channelValue = clawChannel?.value || "other";
    const actionValue = clawAction?.value || "quote";
    const senderText = (clawSender?.value || "").trim();
    const activeConversationId = conversationState.getConversationId();
    const executePayload = {
      content: body,
      channel: channelValue,
      action: actionValue,
      sender_hint: senderText || null,
      tier: selectedProductTier(),
    };
    if (typeof activeConversationId === "string" && activeConversationId) {
      executePayload.conversation_id = activeConversationId;
    }
    return executePayload;
  }

  function clawExecuteWireKey(payload) {
    return JSON.stringify([
      payload.content,
      payload.channel,
      payload.action,
      payload.sender_hint ?? null,
      payload.tier,
      payload.conversation_id ?? null,
    ]);
  }

  // Availability is derived from the request the form would send RIGHT NOW, so it
  // is re-evaluated on every edit rather than released once by an edit event.
  function clawCurrentDispatchIsUncertain() {
    return clawUncertainKeys.size > 0
      && clawUncertainKeys.has(clawExecuteWireKey(clawVisibleExecutePayload()));
  }

  function noteClawContentEdited() {
    if (clawUncertainKeys.size === 0) return;
    setClawButtonsBusy(clawInFlight);
  }

  // Closed parse: integer seconds only, positive. Missing, non-integer, zero,
  // negative and HTTP-date (RFC 7231) values make no countdown claim — the copy
  // then falls back to the safe rate-limit sentence with no fabricated number.
  function parseClawRetryAfter(value) {
    if (typeof value !== "string") return null;
    const raw = value.trim();
    if (!/^[0-9]+$/.test(raw)) return null;
    const seconds = Number.parseInt(raw, 10);
    if (!Number.isFinite(seconds) || seconds < 1) return null;
    return seconds;
  }

  function clawRetryAfterFromResponse(response) {
    try {
      const headers = response && response.headers;
      if (!headers || typeof headers.get !== "function") return null;
      return parseClawRetryAfter(headers.get("Retry-After"));
    } catch (_) {
      return null;
    }
  }

  // Ambiguous = the request may already have reached the engine, so a second
  // POST could double-run it. This is a closed allowlist: on this route the
  // adapter reports Engine unbound/timeout/unreachable and malformed P01
  // responses as `engine_execution_failed` with status 502, and the #830
  // invariant keeps a dispatched or ambiguous failure counted rather than
  // refunded. Every other bounded failure (input, auth, limit, storage,
  // run-history, tier) is a pre-dispatch denial or a post-run persistence
  // problem with its own copy, so it must never claim a possible dispatch.
  function isAmbiguousClawFailure(data, response) {
    const status = response ? response.status : 0;
    const code = data && data.error && typeof data.error.code === "string" ? data.error.code : "";
    return status === 502 || code === "engine_execution_failed";
  }

  function stopClawRetryTimer() {
    if (clawRetryTimer) {
      clearInterval(clawRetryTimer);
      clawRetryTimer = null;
    }
  }

  function clearClawRecovery(options = {}) {
    stopClawRetryTimer();
    clawRetrySeconds = 0;
    if (clawRetryBox) clawRetryBox.hidden = true;
    if (clawRetryCopy) clawRetryCopy.textContent = "";
    if (clawRetryButton) {
      clawRetryButton.disabled = true;
      clawRetryButton.setAttribute("aria-disabled", "true");
    }
    if (clawRetryHint) {
      clawRetryHint.hidden = true;
      clawRetryHint.textContent = "";
      delete clawRetryHint.dataset.localeKey;
    }
    if (options.syncControls) setClawButtonsBusy(clawInFlight);
  }

  function renderClawRetryBox() {
    const remaining = clawRetryRemaining();
    if (clawRetryCopy) {
      clawRetryCopy.textContent = remaining > 0
        ? clawT("claw-retry-waiting", { seconds: remaining })
        : clawT("claw-retry-ready");
    }
    if (clawRetryButton) {
      clawRetryButton.disabled = remaining > 0;
      clawRetryButton.setAttribute("aria-disabled", remaining > 0 ? "true" : "false");
    }
  }

  function beginClawRetryCooldown(seconds) {
    stopClawRetryTimer();
    clawRetrySeconds = seconds;
    if (clawRetryHint) {
      clawRetryHint.hidden = true;
      clawRetryHint.textContent = "";
      delete clawRetryHint.dataset.localeKey;
    }
    if (clawRetryBox) clawRetryBox.hidden = false;
    renderClawRetryBox();
    setClawButtonsBusy(clawInFlight);
    clawRetryTimer = setInterval(() => {
      clawRetrySeconds = clawRetrySeconds > 0 ? clawRetrySeconds - 1 : 0;
      if (clawRetrySeconds === 0) stopClawRetryTimer();
      renderClawRetryBox();
      setClawButtonsBusy(clawInFlight);
    }, 1000);
  }

  function showClawAmbiguousRecoveryHint() {
    if (!clawRetryHint) return;
    stopClawRetryTimer();
    clawRetrySeconds = 0;
    // The request may already be running, so its exact content is recorded as
    // uncertain. The finally block releases the busy flag, so without this the
    // execute button would reopen on an unresolved run.
    if (clawLastDispatchKey) clawUncertainKeys.add(clawLastDispatchKey);
    if (clawRetryBox) clawRetryBox.hidden = true;
    if (clawRetryCopy) clawRetryCopy.textContent = "";
    if (clawRetryButton) {
      clawRetryButton.disabled = true;
      clawRetryButton.setAttribute("aria-disabled", "true");
    }
    clawRetryHint.dataset.localeKey = "claw-error-check-runs";
    clawRetryHint.textContent = clawT("claw-error-check-runs");
    clawRetryHint.hidden = false;
    setClawButtonsBusy(clawInFlight);
  }

  // ── In-flight elapsed wait (#2763) ──────────────────────────────────────
  //
  // The execute POST is a single synchronous browser request: no server-side
  // progress, phase, or completion-percentage source exists, and B54 owns no
  // cancellation authority. So this surface shows only what the browser truly
  // knows — how long the user has been waiting. It never polls the run-history
  // route, never re-dispatches, never infers an Engine/P01 stage, and shows no
  // percentage, phase list, or Cancel control.
  //
  // One 1000ms ticker per in-flight request, started only by explicit user
  // dispatch. A tick re-renders copy from state; it issues no network call and
  // cannot reach the execute entry point. The ticking value is a role="timer"
  // region (implicitly aria-live off), readable on demand without announcing
  // every second; only the two bounded long-wait states are announced, through
  // the single canonical polite status region.
  const CLAW_WAIT_TICK_MS = 1000;
  const CLAW_WAIT_REVEAL_MS = 3000;
  const CLAW_WAIT_LONG_SECONDS = 10;
  const CLAW_WAIT_VERY_LONG_SECONDS = 30;

  function clawWaitElapsedSeconds() {
    if (!clawWaitStartedAt) return 0;
    const elapsed = Date.now() - clawWaitStartedAt;
    return elapsed > 0 ? Math.floor(elapsed / 1000) : 0;
  }

  function clawWaitStageFor(elapsedSeconds) {
    if (elapsedSeconds >= CLAW_WAIT_VERY_LONG_SECONDS) return 2;
    if (elapsedSeconds >= CLAW_WAIT_LONG_SECONDS) return 1;
    return 0;
  }

  function clawWaitStageKey(stage) {
    return stage >= 2 ? "claw-wait-very-long" : "claw-wait-long";
  }

  // Bounded reassurance copy: at most two announcements per request, and the
  // copy carries no elapsed value so the live region is never re-announced once
  // per second.
  function applyClawWaitStageCopy() {
    if (clawWaitAnnouncedStage < 1) return;
    const key = clawWaitStageKey(clawWaitAnnouncedStage);
    setClawStatus(clawT(key), "running", key);
  }

  // Presentation only. Returns true while it owns the status region, so a locale
  // switch re-renders from state (elapsed value preserved) instead of resolving
  // a stale key on its own.
  function renderClawWait() {
    if (!clawWaitStartedAt) return false;
    const elapsed = clawWaitElapsedSeconds();
    if (!clawWaitRevealed && elapsed * 1000 >= CLAW_WAIT_REVEAL_MS) clawWaitRevealed = true;
    if (clawWait) {
      clawWait.hidden = !clawWaitRevealed;
      if (clawWaitRevealed) clawWait.textContent = clawT("claw-wait-elapsed", { seconds: elapsed });
    }
    const stage = clawWaitStageFor(elapsed);
    if (stage > clawWaitAnnouncedStage) {
      clawWaitAnnouncedStage = stage;
      applyClawWaitStageCopy();
    }
    return clawWaitAnnouncedStage > 0;
  }

  function beginClawWait() {
    clearClawWait();
    clawWaitStartedAt = Date.now();
    clawWaitTimer = setInterval(() => {
      renderClawWait();
    }, CLAW_WAIT_TICK_MS);
  }

  // Idempotent teardown: it only ever stops, never starts, so a completion that
  // arrives after a clear can never resurrect a wait.
  function clearClawWait() {
    if (clawWaitTimer) {
      clearInterval(clawWaitTimer);
      clawWaitTimer = null;
    }
    clawWaitStartedAt = 0;
    clawWaitRevealed = false;
    clawWaitAnnouncedStage = 0;
    if (clawWait) {
      clawWait.hidden = true;
      clawWait.textContent = "";
    }
  }

  // A generated document always retains its original bounded download action.
  // #3932 preview is separate and only appears for an actual PDF receipt,
  // with fresh server-side tenant validation and real PDF bytes.
  function setClawDocumentAction(enabled, documentId, filename) {
    const btn = clawResultDocx;
    if (!btn) return;
    btn.disabled = !enabled;
    btn.setAttribute("aria-disabled", enabled ? "false" : "true");
    btn.classList.toggle("is-prominent", enabled);
    if (enabled) {
      btn.dataset.documentId = documentId;
      if (filename) btn.dataset.filename = filename;
      return;
    }
    // Clearing drops the descriptor with the result, so a later click can never
    // replay a previous run's artifact id or filename hint.
    delete btn.dataset.documentId;
    delete btn.dataset.filename;
  }

  let clawPdfPreviewController = null;
  function clearClawArtifact() {
    clawPdfPreviewController?.clear();
    if (clawArtifactMeta) clawArtifactMeta.hidden = true;
    if (clawArtifactName) clawArtifactName.textContent = "";
    if (clawArtifactSize) clawArtifactSize.textContent = "";
    if (clawResultSuccessNote) clawResultSuccessNote.hidden = true;
    setClawDocumentAction(false);
    const downloadLabel = clawResultDocx?.querySelector?.('[data-locale-key="claw-result-docx"]');
    if (downloadLabel) downloadLabel.textContent = clawT("claw-result-docx");
  }

  function formatClawBytes(bytes) {
    if (!Number.isFinite(bytes) || bytes < 0) return "";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function renderClawArtifactMeta(artifact) {
    if (!artifact || !artifact.document_id) {
      clearClawArtifact();
      return;
    }
    const filename = typeof artifact.filename === "string" && artifact.filename ? artifact.filename : "document.docx";
    const byteLength = typeof artifact.byte_length === "number" ? artifact.byte_length : null;
    if (clawArtifactName) clawArtifactName.textContent = filename;
    if (clawArtifactSize) clawArtifactSize.textContent = byteLength != null ? formatClawBytes(byteLength) : "";
    if (clawArtifactMeta) clawArtifactMeta.hidden = false;
    if (clawResultSuccessNote) clawResultSuccessNote.hidden = false;
    setClawDocumentAction(true, artifact.document_id, artifact.filename);
    const downloadLabel = clawResultDocx?.querySelector?.('[data-locale-key="claw-result-docx"]');
    if (downloadLabel) downloadLabel.textContent = artifact.media_type === "application/pdf"
      ? clawT("claw-result-pdf")
      : clawT("claw-result-docx");
    if (!clawPdfPreviewController && clawArtifactMeta && window.PadiemClawPdfPreview?.create) {
      clawPdfPreviewController = window.PadiemClawPdfPreview.create({
        mount: clawArtifactMeta,
        onError: (message) => setClawStatus(message, "error"),
      });
    }
    clawPdfPreviewController?.set(artifact);
  }

  function safeClawErrorMessage(data, response) {
    const code = data && data.error && typeof data.error.code === "string" ? data.error.code : "";
    const status = response ? response.status : 0;
    // #3933: a bounded pre-dispatch refusal is a product state, not a run that
    // started and then failed. The manual-intake route returns this same
    // `tier_unavailable` code before it ever dispatches, so resolving it through
    // the shared bounded-refusal authority keeps this lane's wording identical to
    // the composer and live SSE lanes instead of the generic "the run failed"
    // sentence. An unlisted code falls through to the existing bounded copy.
    const bounded = clawBoundedRefusalCopy(code);
    if (bounded) return bounded.message;
    if (code === "invalid_content" || code === "content_too_short") return clawT("claw-error-empty");
    if (code === "content_too_long" || code === "body_too_large" || status === 413) return clawT("claw-error-too-large");
    if (code === "invalid_channel" || code === "invalid_action" || code === "unsupported_media_type" || code === "invalid_sender_hint") return clawT("claw-error-invalid");
    if (code === "rate_limited" || status === 429) return clawT("claw-error-rate-limited");
    if (code === "workspace_scope_unavailable" || code === "live_identity_unavailable") return clawT("claw-error-auth-unavailable");
    if (code === "auth_required" || status === 401) return clawT("claw-error-auth-needed");
    if (code === "workspace_storage_unavailable" || code === "artifact_storage_failed" || code === "artifact_generation_failed") return clawT("claw-error-storage");
    if (status === 503 || code === "engine_not_configured" || code === "live_abuse_gate_unavailable") return clawT("claw-error-generic");
    if (code === "engine_execution_failed" || status === 502) return clawT("claw-error-generic");
    return clawT("claw-error-generic");
  }

  async function downloadClawArtifact(documentId, filenameHint) {
    if (!documentId || !/^doc_[A-Za-z0-9]{32}$/.test(String(documentId))) return;
    try {
      const resp = await fetch(`/api/claw/manual-intake/artifact/${encodeURIComponent(documentId)}`, { cache: "no-store" });
      if (!resp.ok) {
        const err = await resp.json().catch(() => null);
        setClawStatus(safeClawErrorMessage(err, resp), "error");
        setClawAreaState("error");
        return;
      }
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filenameHint || "document.docx";
      a.rel = "noopener";
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 4000);
    } catch (_) {
      setClawStatus(clawT("claw-error-generic"), "error");
      setClawAreaState("error");
    }
  }

  function resetClawAutomationState(...a) { return automationModule().resetClawAutomationState(...a); }

  function setClawAutomationLoading(...a) { return automationModule().setClawAutomationLoading(...a); }

  function setClawAutomationError(...a) { return automationModule().setClawAutomationError(...a); }

  function setClawAutomationForbidden(...a) { return automationModule().setClawAutomationForbidden(...a); }

  function renderClawAutomationRules(...a) { return automationModule().renderClawAutomationRules(...a); }

  async function loadClawAutomationRules(...a) { return automationModule().loadClawAutomationRules(...a); }

  function setClawAutomationEditStatus(...a) { return automationFormModule().setClawAutomationEditStatus(...a); }

  function syncClawAutomationEditFields(...a) { return automationFormModule().syncClawAutomationEditFields(...a); }

  function clawAutomationEditExpression(...a) { return automationFormModule().clawAutomationEditExpression(...a); }

  function findRuleEditButton(...a) { return automationFormModule().findRuleEditButton(...a); }


  function openClawAutomationEdit(...a) { return automationFormModule().openClawAutomationEdit(...a); }

  function closeClawAutomationEdit(...a) { return automationFormModule().closeClawAutomationEdit(...a); }

  async function submitClawAutomationEdit(...a) { return automationFormModule().submitClawAutomationEdit(...a); }

  if (clawAutomationEditForm) {
    clawAutomationEditForm.addEventListener("submit", (event) => {
      void submitClawAutomationEdit(event);
    });
  }
  if (clawAutomationEditKind) {
    clawAutomationEditKind.addEventListener("change", syncClawAutomationEditFields);
  }
  if (clawAutomationEditCancel) {
    clawAutomationEditCancel.addEventListener("click", () => closeClawAutomationEdit());
  }

  function setClawAutomationToggleStatus(...a) { return automationModule().setClawAutomationToggleStatus(...a); }

  function findRuleToggleButton(...a) { return automationModule().findRuleToggleButton(...a); }

  function focusRuleToggleAfterReload(...a) { return automationModule().focusRuleToggleAfterReload(...a); }

  async function toggleClawAutomationRule(...a) { return automationModule().toggleClawAutomationRule(...a); }

  // --- #3257 Web Automation Create -------------------------------------------
  // Seven product fields only; the server rejects any authority field and owns
  // rule id, owner provenance, membership role and the execution target.
  let clawAutomationCreateInFlight = false;

  function setClawAutomationCreateStatus(...a) { return automationFormModule().setClawAutomationCreateStatus(...a); }

  function syncClawAutomationCreateFields(...a) { return automationFormModule().syncClawAutomationCreateFields(...a); }

  function clawAutomationCreateExpression(...a) { return automationFormModule().clawAutomationCreateExpression(...a); }

  function resetClawAutomationCreateForm(...a) { return automationFormModule().resetClawAutomationCreateForm(...a); }

  function closeClawAutomationCreate(...a) { return automationFormModule().closeClawAutomationCreate(...a); }

  function scrollClawAutomationCreateIntoView(...a) { return automationFormModule().scrollClawAutomationCreateIntoView(...a); }

  async function submitClawAutomationCreate(...a) { return automationFormModule().submitClawAutomationCreate(...a); }

  if (clawAutomationCreateForm) {
    clawAutomationCreateForm.addEventListener("submit", (event) => {
      void submitClawAutomationCreate(event);
    });
  }
  if (clawAutomationCreateKind) {
    clawAutomationCreateKind.addEventListener("change", syncClawAutomationCreateFields);
  }
  if (clawAutomationCreateCancel) {
    clawAutomationCreateCancel.addEventListener("click", () => {
      resetClawAutomationCreateForm();
      closeClawAutomationCreate();
    });
  }
  if (clawAutomationCreate) {
    clawAutomationCreate.addEventListener("toggle", () => {
      // The header button owns the disclosure, so it carries the state.
      if (clawAutomationCreateOpen) {
        clawAutomationCreateOpen.setAttribute(
          "aria-expanded", clawAutomationCreate.open ? "true" : "false",
        );
      }
      if (clawAutomationCreate.open) {
        setClawAutomationCreateStatus(null);
        if (clawAutomationCreateName) clawAutomationCreateName.focus();
      } else if (clawAutomationCreateOpen) {
        clawAutomationCreateOpen.focus();
      }
    });
  }
  if (clawAutomationCreateOpen) {
    if (!clawAutomationCreate) {
      // No form to open, so the control is not offered at all.
      clawAutomationCreateOpen.hidden = true;
    } else {
      clawAutomationCreateOpen.addEventListener("click", () => {
        clawAutomationCreate.open = !clawAutomationCreate.open;
        // On a narrow window the form sits below the rule list, so the view
        // follows the user to it instead of leaving the input off-screen.
        if (clawAutomationCreate.open) {
          scrollClawAutomationCreateIntoView();
        }
      });
    }
  }

  // Standalone Automation page: the existing #clawAutomation section is moved
  // once into #automationViewBody. Moving (not cloning) preserves every bound
  // listener and all getElementById handles, so list/create/edit/toggle/
  // status/alerts and the permission/workspace checks run against the same
  // APIs and store. An enabled rule list never claims the scheduler itself
  // is running; the existing scheduler note stays verbatim.
  let automationViewMounted = false;
  function mountAutomationView(...a) { return automationModule().mountAutomationView(...a); }

  function openClawAutomation(...a) { return automationModule().openClawAutomation(...a); }

  if (automationNavButton) automationNavButton.addEventListener("click", openClawAutomation);
  // #4462: automation-related run/completion/failure alerts stay reachable
  // from the automation view after the standalone sidebar Alerts entry is gone.
    if (clawAutomationRetry) clawAutomationRetry.addEventListener("click", () => void loadClawAutomationRules());
  function setClawAutomationRetryVisible(...a) { return automationModule().setClawAutomationRetryVisible(...a); }

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
    if (clawAutomation) clawAutomation.hidden = true;
    if (clawManualForm) clawManualForm.hidden = true;
    if (clawResultArea) clawResultArea.hidden = false;
    setNavActive();
    input.focus();
    closeSidebar();
    syncApprovedMemoryVisibility();
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
    if (clawAutomation) clawAutomation.hidden = true;
    if (clawManualForm) clawManualForm.hidden = false;
    if (clawResultArea) clawResultArea.hidden = false;
    setNavActive();
    input.focus();
    closeSidebar();
    syncApprovedMemoryVisibility();
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
      if (!redirect) throw new Error("drive authorization unavailable");
      window.location.assign(redirect);
    } catch (_) {
      // Bounded failure with no automatic retry: only a new explicit user
      // gesture starts another attempt, and this attempt's state is dropped.
      googleConnectorConnectInFlight = false;
      button.disabled = false;
      setConnectorCopy(button, "connectors-connect-drive");
      if (connectorsError) {
        setConnectorCopy(connectorsError, "connectors-connect-drive-error");
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
      if (!redirect) throw new Error("gmail authorization unavailable");
      window.location.assign(redirect);
    } catch (_) {
      // Bounded failure with no automatic retry: only a new explicit user
      // gesture starts another attempt, and this attempt's state is dropped.
      googleConnectorConnectInFlight = false;
      button.disabled = false;
      setConnectorCopy(button, "connectors-connect-gmail");
      if (connectorsError) {
        setConnectorCopy(connectorsError, "connectors-connect-drive-error");
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

  function revealClawCard(kindText, executed = false) {
    if (clawResultEmpty) clawResultEmpty.hidden = true;
    if (clawResultHint) clawResultHint.hidden = true;
    if (clawResultCard) clawResultCard.hidden = false;
    if (clawResultKind) clawResultKind.textContent = kindText || "";
    if (clawResultBadge) {
      clawResultBadge.dataset.localeKey = executed ? "claw-result-badge-run" : "claw-result-badge";
      clawResultBadge.textContent = clawT(executed ? "claw-result-badge-run" : "claw-result-badge");
    }
  }

  function approvalDecisionErrorMessage(...a) { return conversationModule().approvalDecisionErrorMessage(...a); }

  function setApprovalControlsBusy(container, busy) {
    if (!container) return;
    Array.from(container.children || []).forEach((child) => {
      if (String(child.tagName || "").toUpperCase() === "BUTTON") {
        child.disabled = busy;
        child.setAttribute("aria-disabled", String(busy));
      }
    });
  }

  function renderClawApprovalControls(container, runId, onResolved) {
    if (!container || typeof runId !== "string" || !runId) return;
    container.replaceChildren();
    container.hidden = false;

    const copy = document.createElement("p");
    copy.className = "claw-approval-copy";
    copy.textContent = clawT("claw-approval-required");

    const status = document.createElement("p");
    status.className = "claw-approval-status";
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    status.hidden = true;

    const approve = document.createElement("button");
    approve.type = "button";
    approve.className = "claw-approval-button claw-approval-approve";
    approve.textContent = clawT("claw-approval-approve");

    const deny = document.createElement("button");
    deny.type = "button";
    deny.className = "claw-approval-button claw-approval-deny";
    deny.textContent = clawT("claw-approval-deny");

    async function decide(decision) {
      if (clawApprovalInFlight) return;
      clawApprovalInFlight = true;
      // The session generation this decision belongs to, captured before any
      // await. An auth loss or account switch bumps the epoch, so a response
      // that lands afterwards is stale and must not be presented.
      const decisionEpoch = clawApprovalEpoch;
      setApprovalControlsBusy(container, true);
      status.hidden = false;
      status.dataset.state = "pending";
      status.textContent = clawT("claw-approval-processing");
      try {
        const response = await fetch("/api/claw/approvals/decision", {
          method: "POST",
          headers: { "Content-Type": "application/json", "Accept": "application/json" },
          body: JSON.stringify({ run_id: runId, decision }),
        });
        const data = await response.json().catch(() => null);
        // A decision begun before the session changed is not a license to
        // present its result to the new (or signed-out) session.
        if (decisionEpoch !== clawApprovalEpoch || authState.authenticated !== true) return;
        if (!response.ok || !data || data.ok !== true || !data.result || typeof data.result.run_id !== "string") {
          throw mappedUiError(approvalDecisionErrorMessage(data, response), data);
        }
        status.hidden = true;
        status.removeAttribute("data-state");
        invalidateClawRunsRead();
        if (typeof onResolved === "function") await onResolved(data.result);
      } catch (error) {
        if (decisionEpoch !== clawApprovalEpoch || authState.authenticated !== true) return;
        status.hidden = false;
        status.dataset.state = "error";
        status.textContent = safeLocalUiMessage(error, clawT("claw-approval-error"));
        const reference = failureCodeNote(error?.code, "");
        if (reference) status.appendChild(reference);
      } finally {
        // A stale decision must not release the busy state of a newer
        // session's controls; the invalidation path already reset the shared
        // single-flight flag.
        if (decisionEpoch === clawApprovalEpoch) {
          clawApprovalInFlight = false;
          setApprovalControlsBusy(container, false);
        }
      }
    }

    approve.addEventListener("click", () => decide("approve"));
    deny.addEventListener("click", () => decide("deny"));
    container.append(copy, approve, deny, status);
  }

  function clearImmediateApprovalControls() {
    if (!clawApprovalActions) return;
    clawApprovalActions.replaceChildren();
    clawApprovalActions.hidden = true;
  }

  async function applyImmediateApprovalDecision(result) {
    if (!result || typeof result.run_id !== "string") return;
    // Session authority was already adopted from the canonical execute response.
    // Approval continuation may return the same handle for presentation, but the
    // browser must not introduce a second conversation-id adoption path.
    const status = typeof result.status === "string" ? result.status : "";
    if (status === "waiting_approval" && result.approval_required === true) {
      if (clawResultPreview) clawResultPreview.textContent = clawT("claw-approval-required");
      renderClawApprovalControls(clawApprovalActions, result.run_id, applyImmediateApprovalDecision);
      setClawStatus(clawT("claw-approval-required"), "waiting_approval");
      setClawAreaState("waiting_approval");
    } else {
      clearImmediateApprovalControls();
      const resultText = typeof result.result_text === "string" && result.result_text
        ? result.result_text
        : clawRunStatusLabel(status);
      if (clawResultPreview) clawResultPreview.textContent = resultText;
      setClawStatus(resultText, status || "success");
      setClawAreaState(status || "success");
    }
    await loadClawRunHistory();
  }

  // #2532 (R2): echo the submitted request as a user bubble in the shared
  // conversation so manual Claw reads as one continuous Chat thread. This is
  // the user's own message, never presented as an AI result.
  function renderClawRequestEcho(text) {
    if (!clawRequestEcho || !clawRequestEchoText) return;
    clawRequestEchoText.textContent = text;
    clawRequestEcho.hidden = false;
  }

  // Single artifact handler: reads the current dataset at click time (no
  // per-result listener leak), and is the only control wired to the download.
  if (clawResultDocx) clawResultDocx.addEventListener("click", () => {
    const docId = clawResultDocx.dataset.documentId;
    const fname = clawResultDocx.dataset.filename;
    if (docId && !clawResultDocx.disabled) downloadClawArtifact(docId, fname);
  });

  if (clawManualForm) {
    clawManualForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (clawInFlight) return;
      const body = (input.value || "").trim();
      if (!body) {
        if (clawResultCard) clawResultCard.hidden = true;
        clearClawArtifact();
        if (clawResultEmpty) {
          clawResultEmpty.hidden = false;
          clawResultEmpty.textContent = clawT("claw-error-empty");
        }
        if (clawResultHint) clawResultHint.hidden = false;
        setClawStatus(clawT("claw-error-empty"), "error");
        setClawAreaState("error");
        input.focus();
        return;
      }
      const channelValue = clawChannel?.value || "other";
      const actionValue = clawAction?.value || "quote";
      const channelText = clawChannel?.options[clawChannel.selectedIndex]?.textContent || channelValue;
      const actionText = clawAction?.options[clawAction.selectedIndex]?.textContent || actionValue;
      const senderText = (clawSender?.value || "").trim();

      renderClawRequestEcho(body);
      setClawButtonsBusy(true);
      setClawStatus(clawT("claw-status-preview-running"), "running", "claw-status-preview-running");
      setClawAreaState("submitting");
      if (clawResultCard) clawResultCard.hidden = true;
      clearClawArtifact();
      if (clawResultEmpty) {
        clawResultEmpty.hidden = false;
        clawResultEmpty.textContent = clawT("claw-status-preview-running");
      }

      const renderPreviewError = () => {
        if (clawResultCard) clawResultCard.hidden = true;
        clearClawArtifact();
        if (clawMemoryReview) clawMemoryReview.hidden = true;
        if (clawResultEmpty) {
          clawResultEmpty.hidden = false;
          clawResultEmpty.textContent = clawT("claw-error-preview");
        }
        if (clawResultHint) clawResultHint.hidden = false;
        setClawStatus(clawT("claw-error-preview"), "error", "claw-error-preview");
        setClawAreaState("error");
      };

      try {
        const response = await fetch("/api/claw/manual-intake/preview", {
          method: "POST",
          headers: { "Content-Type": "application/json", "Accept": "application/json" },
          body: JSON.stringify({ content: body, channel: channelValue, action: actionValue, sender_hint: senderText || null }),
        });
        if (!response.ok) {
          renderPreviewError();
          return;
        }
        const data = await response.json();
        if (!data || !data.ok || !data.preview || typeof data.preview.result_text !== "string") {
          renderPreviewError();
          return;
        }
        const preview = data.preview;
        revealClawCard(preview.title);
        if (clawResultPreview) clawResultPreview.textContent = preview.result_text;
        clearClawArtifact();
        renderMemoryProposalReview(Array.isArray(preview.memory_proposals) ? preview.memory_proposals : []);
        setClawStatus(clawT("claw-status-preview-success"), "success", "claw-status-preview-success");
        setClawAreaState("success");
        // Move focus to result for screen-reader and keyboard users
        if (clawResultPreview) clawResultPreview.focus?.();
      } catch {
        renderPreviewError();
      } finally {
        setClawButtonsBusy(false);
      }
    });
  }

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

  const CLAW_DISPATCH_KEY_WINDOW_MS = 10000;
  // A duplicate listener or a retried click shares the key already claimed by
  // the in-flight dispatch. Without a shared value, two closures would each
  // mint their own key and the server could not recognize the replay.
  function clawClaimDispatchKey() {
    const button = clawExecuteButton;
    const existing = button && button.dataset ? button.dataset.clawDispatchKey : "";
    const existingAt = Number(
      button && button.dataset ? button.dataset.clawDispatchAt || "0" : "0",
    );
    if (existing && Date.now() - existingAt < CLAW_DISPATCH_KEY_WINDOW_MS) {
      return existing;
    }
    // #7133: the random part is minted by the shared transport helper —
    // app.js never calls crypto directly (browser-minting contracts).
    const minted = chatTransport.createRequestId?.();
    const key = minted ? `claw-${minted}` : `claw-${Date.now().toString(36)}`;
    if (button && button.dataset) {
      button.dataset.clawDispatchKey = key;
      button.dataset.clawDispatchAt = String(Date.now());
    }
    return key;
  }
  function releaseClawDispatchKey(key) {
    const button = clawExecuteButton;
    if (!button || !button.dataset || button.dataset.clawDispatchKey !== key) return;
    delete button.dataset.clawDispatchKey;
    delete button.dataset.clawDispatchAt;
  }

  // Single execute entry point. The primary button and the post-cooldown retry
  // button both funnel through here, so a retry can never bypass the
  // single-flight, pre-dispatch cooldown or uncertain-dispatch guards and the
  // payload is always rebuilt from the currently visible form at click time.
  async function runClawExecution() {
    if (clawInFlight) return;
    if (clawRetryRemaining() > 0) return; // explicit retry only after the pre-dispatch cooldown
    if (clawCurrentDispatchIsUncertain()) return; // #3382: no re-send of an unresolved request
    const executePayload = clawVisibleExecutePayload();
    const body = executePayload.content;
    if (!body) {
      clearClawArtifact();
      if (clawResultCard) clawResultCard.hidden = true;
      if (clawResultEmpty) {
        clawResultEmpty.hidden = false;
        clawResultEmpty.textContent = clawT("claw-error-empty");
      }
      setClawStatus(clawT("claw-error-empty"), "error");
      setClawAreaState("error");
      input.focus();
      return;
    }
    const idempotencyKey = clawClaimDispatchKey();
    clearClawRecovery();
    // Remember the exact bytes this dispatch carried, so a later ambiguous
    // failure can tell an identical re-send apart from new work.
    clawLastDispatchKey = clawExecuteWireKey(executePayload);
    renderClawRequestEcho(body);
    setClawButtonsBusy(true);
    // Explicit user dispatch is the only thing that may start a wait timer.
    beginClawWait();
    setClawStatus(clawT("claw-status-execute-running"), "running", "claw-status-execute-running");
    setClawAreaState("submitting");
    if (clawResultCard) clawResultCard.hidden = true;
    clearImmediateApprovalControls();
    clearClawArtifact();
    if (clawResultEmpty) {
      clawResultEmpty.hidden = false;
      clawResultEmpty.textContent = clawT("claw-status-execute-running");
    }

    try {
      const response = await fetch("/api/claw/manual-intake/execute", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Accept": "application/json",
          "Idempotency-Key": idempotencyKey,
        },
        body: JSON.stringify(executePayload),
      });
      const data = await response.json().catch(() => null);
      if (data && data.ok && data.result) {
        const result = data.result;
        // Server-echoed canonical handle only (#2916): reuse it as the single
        // session authority; never build a second id here.
        if (typeof result.conversation_id === "string" && result.conversation_id) {
          conversationState.setConversationId(result.conversation_id, PRODUCT_CLAW);
        }
        if (
          result.status === "waiting_approval"
          && result.approval_required === true
          && typeof result.request_id === "string"
          && result.request_id
        ) {
          revealClawCard(result.title, true);
          clearClawArtifact();
          if (clawResultPreview) clawResultPreview.textContent = clawT("claw-approval-required");
          renderClawApprovalControls(clawApprovalActions, result.request_id, applyImmediateApprovalDecision);
          setClawStatus(clawT("claw-approval-required"), "waiting_approval");
          setClawAreaState("waiting_approval");
          if (clawResultPreview) clawResultPreview.focus?.();
          return;
        }
        if (typeof result.result_text !== "string") {
          throw new Error(clawT("claw-error-generic"));
        }
        clearImmediateApprovalControls();
        const safeText = String(result.result_text);
        revealClawCard(result.title, true);
        if (clawResultPreview) clawResultPreview.textContent = safeText;
        if (clawResultEmpty) clawResultEmpty.hidden = true;
        const artifact = result.artifact && typeof result.artifact.document_id === "string" ? result.artifact : null;
        const hasArtifact = !!(artifact && artifact.document_id);
        if (hasArtifact) renderClawArtifactMeta(artifact); else clearClawArtifact();
        setClawStatus(clawT("claw-status-execute-success"), "success", "claw-status-execute-success");
        setClawAreaState("success");
        if (hasArtifact && clawResultDocx) clawResultDocx.focus?.();
        else if (clawResultPreview) clawResultPreview.focus?.();
        return;
      }
      const safeMsg = safeClawErrorMessage(data, response);
      // #3933: a bounded pre-dispatch refusal also states, in the result area,
      // that the request was never executed — the distinction the status line
      // alone cannot carry. Resolved from the same authority as safeMsg.
      const boundedFailure = clawBoundedRefusalCopy(
        data && data.error && typeof data.error.code === "string" ? data.error.code : "",
      );
      if (clawResultEmpty) {
        clawResultEmpty.hidden = false;
        clawResultEmpty.textContent = boundedFailure
          ? `${boundedFailure.message} ${boundedFailure.hint}`
          : safeMsg;
      }
      setClawStatus(safeMsg, "error");
      setClawAreaState("error");
      // A 429 usage denial happens before dispatch, so its Retry-After may be
      // honored as a cooldown. Anything ambiguous gets guidance, never a retry.
      // #3933: a bounded pre-dispatch refusal provably never dispatched, so it is
      // excluded here as well as in the classifier — widening the ambiguous set
      // later must not be able to latch a HOLD as an uncertain run.
      const retryAfter = response.status === 429 ? clawRetryAfterFromResponse(response) : null;
      if (retryAfter !== null) beginClawRetryCooldown(retryAfter);
      else if (!boundedFailure && isAmbiguousClawFailure(data, response)) showClawAmbiguousRecoveryHint();
    } catch {
      const fallback = clawT("claw-error-generic");
      if (clawResultEmpty) {
        clawResultEmpty.hidden = false;
        clawResultEmpty.textContent = fallback;
      }
      setClawStatus(fallback, "error");
      setClawAreaState("error");
      // The request may have reached the engine before the connection died.
      showClawAmbiguousRecoveryHint();
    } finally {
      // The owning request always tears its wait timer down: success, known
      // pre-dispatch denial, ambiguous failure, and auth loss all clear it.
      clearClawWait();
      releaseClawDispatchKey(idempotencyKey);
      setClawButtonsBusy(false);
    }
  }

  if (clawExecuteButton) {
    if (clawExecuteButton.dataset.clawExecuteWired !== "1") {
      clawExecuteButton.dataset.clawExecuteWired = "1";
      clawExecuteButton.addEventListener("click", () => {
        void runClawExecution();
      });
    }
  }
  if (clawRetryButton) {
    if (clawRetryButton.dataset.clawRetryWired !== "1") {
      clawRetryButton.dataset.clawRetryWired = "1";
      clawRetryButton.addEventListener("click", () => {
        void runClawExecution();
      });
    }
  }
  // #3382: composing different work — new text, channel, action,
  // sender or conversation — is what releases the uncertain-dispatch latch.
  [input, clawChannel, clawAction, clawSender].forEach((node) => {
    if (!node || typeof node.addEventListener !== "function") return;
    node.addEventListener("input", noteClawContentEdited);
    node.addEventListener("change", noteClawContentEdited);
  });
  // Approved-memory review UI (#2340)
  const clawApprovedMemory = document.getElementById("clawApprovedMemory");
  // #4488 Phase A: the approved-memory panel is progressive disclosure on the
  // Claw entry; its <details> wrapper is hidden whenever the panel is.
  const clawApprovedDisclosure = document.getElementById("clawApprovedDisclosure");
  const clawApprovedRefresh = document.getElementById("clawApprovedRefresh");
  const clawApprovedLoading = document.getElementById("clawApprovedLoading");
  const clawApprovedError = document.getElementById("clawApprovedError");
  const clawApprovedList = document.getElementById("clawApprovedList");
  const clawApprovedEmpty = document.getElementById("clawApprovedEmpty");
  const clawMemoryReview = document.getElementById("clawMemoryReview");

  let approvedMemoryInFlight = false;

  function setApprovedMemoryStatus(message, state, code = "") {
    if (!clawApprovedError) return;
    if (!message) {
      clawApprovedError.hidden = true;
      clawApprovedError.textContent = "";
      clawApprovedError.removeAttribute("data-state");
      return;
    }
    clawApprovedError.hidden = false;
    clawApprovedError.textContent = message;
    const reference = failureCodeNote(code, "");
    if (reference) clawApprovedError.appendChild(reference);
    if (state) clawApprovedError.dataset.state = state;
    else clawApprovedError.removeAttribute("data-state");
  }

  function approvedMemoryErrorMessage(...a) { return conversationModule().approvedMemoryErrorMessage(...a); }

  // Proposal review surface: rendered from preview memory_proposals. Approve is
  // impossible until the user explicitly approves; reject never persists.
  function renderMemoryProposalReview(proposals) {
    if (!clawMemoryReview) return;
    clawMemoryReview.replaceChildren();
    if (!Array.isArray(proposals) || proposals.length === 0) {
      clawMemoryReview.hidden = true;
      return;
    }
    const heading = document.createElement("h3");
    heading.className = "claw-memory-review-title";
    heading.textContent = clawT("claw-memory-review-title");
    clawMemoryReview.appendChild(heading);
    proposals.forEach((proposal) => {
      if (!proposal || typeof proposal !== "object") return;
      const safe = {
        type: typeof proposal.type === "string" ? proposal.type : "",
        name: typeof proposal.name === "string" ? proposal.name : "",
        note: typeof proposal.note === "string" ? proposal.note : "",
        source_channel: typeof proposal.source_channel === "string" ? proposal.source_channel : "",
      };
      const card = document.createElement("div");
      card.className = "claw-memory-proposal";
      const title = document.createElement("strong");
      title.className = "claw-memory-proposal-name";
      title.textContent = safe.name;
      const meta = document.createElement("span");
      meta.className = "claw-memory-proposal-type";
      meta.textContent = safe.type;
      const note = document.createElement("p");
      note.className = "claw-memory-proposal-note";
      note.textContent = safe.note;
      const actions = document.createElement("div");
      actions.className = "claw-memory-proposal-actions";
      const approveBtn = document.createElement("button");
      approveBtn.type = "button";
      approveBtn.className = "claw-memory-approve";
      approveBtn.textContent = clawT("claw-memory-approve");
      approveBtn.addEventListener("click", () => approveProposal(safe));
      const rejectBtn = document.createElement("button");
      rejectBtn.type = "button";
      rejectBtn.className = "claw-memory-reject";
      rejectBtn.textContent = clawT("claw-memory-reject");
      rejectBtn.addEventListener("click", () => rejectProposal(safe));
      actions.append(approveBtn, rejectBtn);
      card.append(title, meta, note, actions);
      clawMemoryReview.appendChild(card);
    });
    clawMemoryReview.hidden = false;
  }

  function proposalBody(proposal) {
    return { type: proposal.type, name: proposal.name, note: proposal.note || null, source_channel: proposal.source_channel || null };
  }

  async function approveProposal(proposal) {
    if (approvedMemoryInFlight) return;
    approvedMemoryInFlight = true;
    setApprovedMemoryStatus("", "");
    try {
      const response = await fetch("/api/claw/memory/approve", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        cache: "no-store",
        body: JSON.stringify({ approved: true, proposal: proposalBody(proposal) }),
      });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || data.ok !== true || !data.memory) {
        throw mappedUiError(approvedMemoryErrorMessage(data, response), data);
      }
      await fetchApprovedMemoryList();
    } catch (error) {
      setApprovedMemoryStatus(safeLocalUiMessage(error, clawT("claw-memory-error-generic")), "error", error?.code);
    } finally {
      approvedMemoryInFlight = false;
    }
  }

  async function rejectProposal(proposal) {
    if (approvedMemoryInFlight) return;
    approvedMemoryInFlight = true;
    setApprovedMemoryStatus("", "");
    try {
      const response = await fetch("/api/claw/memory/reject", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        cache: "no-store",
        body: JSON.stringify({ proposal: proposalBody(proposal) }),
      });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || data.ok !== true || data.persisted !== false) {
        throw mappedUiError(approvedMemoryErrorMessage(data, response), data);
      }
      await fetchApprovedMemoryList();
    } catch (error) {
      setApprovedMemoryStatus(safeLocalUiMessage(error, clawT("claw-memory-error-generic")), "error", error?.code);
    } finally {
      approvedMemoryInFlight = false;
    }
  }

  function renderApprovedMemoryCard(memory) {
    const card = document.createElement("div");
    card.className = "claw-approved-card";
    card.dataset.memoryId = memory.memory_id || "";

    const head = document.createElement("div");
    head.className = "claw-approved-card-head";
    const title = document.createElement("strong");
    title.className = "claw-approved-card-title";
    title.textContent = memory.name || "";
    const badge = document.createElement("span");
    badge.className = "claw-approved-card-badge";
    badge.textContent = memory.status === "approved" ? clawT("claw-memory-status-approved") : uiT("status-unknown");
    head.append(title, badge);

    const meta = document.createElement("div");
    meta.className = "claw-approved-card-meta";
    const memoryTypeKey = `claw-memory-type-${memory.memory_type || ""}`;
    const memoryType = memory.memory_type ? clawT(memoryTypeKey) : "";
    meta.textContent = `${memoryType === memoryTypeKey ? memory.memory_type : memoryType} · ${memory.created_at || ""}`;

    const note = document.createElement("p");
    note.className = "claw-approved-card-note";
    note.textContent = memory.note || "";

    const actions = document.createElement("div");
    actions.className = "claw-approved-card-actions";
    const detailBtn = document.createElement("button");
    detailBtn.type = "button";
    detailBtn.className = "claw-approved-action";
    detailBtn.textContent = clawT("claw-memory-detail");
    detailBtn.addEventListener("click", () => {
      const id = card.dataset.memoryId;
      if (id) loadApprovedMemoryDetail(id);
    });
    actions.appendChild(detailBtn);
    card.append(head, meta, note, actions);
    return card;
  }

  function renderApprovedMemoryDetail(memory) {
    const existing = clawApprovedList?.querySelector(".claw-approved-detail");
    if (existing) existing.remove();
    const detail = document.createElement("div");
    detail.className = "claw-approved-detail";
    const rows = [
      { label: clawT("claw-memory-type"), value: memory.memory_type || "" },
      { label: clawT("claw-memory-name"), value: memory.name || "" },
      { label: clawT("claw-memory-note"), value: memory.note || "" },
      { label: clawT("claw-memory-channel"), value: memory.source_channel || "" },
      { label: clawT("claw-memory-status"), value: memory.status === "approved" ? clawT("claw-memory-status-approved") : uiT("status-unknown") },
      { label: clawT("claw-memory-created"), value: memory.created_at || "" },
      { label: clawT("claw-memory-updated"), value: memory.updated_at || "" },
    ];
    rows.forEach((row) => {
      const rowEl = document.createElement("div");
      rowEl.className = "claw-approved-detail-row";
      const label = document.createElement("span");
      label.className = "claw-approved-detail-label";
      label.textContent = row.label;
      const value = document.createElement("span");
      value.className = "claw-approved-detail-value";
      value.textContent = row.value;
      rowEl.append(label, value);
      detail.appendChild(rowEl);
    });
    const closeBtn = document.createElement("button");
    closeBtn.type = "button";
    closeBtn.className = "claw-approved-action";
    closeBtn.textContent = clawT("claw-memory-close");
    closeBtn.addEventListener("click", () => {
      detail.remove();
      loadApprovedMemoryList();
    });
    detail.appendChild(closeBtn);
    clawApprovedList?.appendChild(detail);
  }

  // Unguarded fetch: callers hold the single-flight flag while awaiting this.
  async function fetchApprovedMemoryList() {
    if (!clawApprovedMemory) return;
    setApprovedMemoryStatus("", "");
    if (clawApprovedLoading) clawApprovedLoading.hidden = false;
    if (clawApprovedList) clawApprovedList.hidden = true;
    if (clawApprovedEmpty) clawApprovedEmpty.hidden = true;
    if (clawApprovedList) clawApprovedList.replaceChildren();
    try {
      const response = await fetch("/api/claw/memory", { headers: { "Accept": "application/json" }, cache: "no-store" });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || !Array.isArray(data.memories)) {
        throw mappedUiError(approvedMemoryErrorMessage(data, response), data);
      }
      if (clawApprovedLoading) clawApprovedLoading.hidden = true;
      if (clawApprovedList) clawApprovedList.hidden = false;
      if (data.memories.length === 0) {
        if (clawApprovedEmpty) clawApprovedEmpty.hidden = false;
        return;
      }
      data.memories.forEach((memory) => {
        if (!memory || typeof memory.memory_id !== "string") return;
        clawApprovedList?.appendChild(renderApprovedMemoryCard(memory));
      });
      // #5882: when the server returns a next cursor, append "load more" and keep the cursor on the button.
      if (clawApprovedList && typeof data.next_cursor === "string" && data.next_cursor) {
        const more = document.createElement("button");
        more.type = "button";
        more.className = "recent-item memory-more";
        more.id = "clawApprovedMore";
        more.dataset.cursor = data.next_cursor;
        more.textContent = uiT("projects-more");
        more.addEventListener("click", () => { void loadMoreApprovedMemories(more.dataset.cursor); });
        clawApprovedList.appendChild(more);
      }
    } catch (error) {
      if (clawApprovedLoading) clawApprovedLoading.hidden = true;
      setApprovedMemoryStatus(safeLocalUiMessage(error, clawT("claw-memory-error-generic")), "error", error?.code);
    }
  }

  async function loadApprovedMemoryList() {
    if (approvedMemoryInFlight) return;
    approvedMemoryInFlight = true;
    try {
      await fetchApprovedMemoryList();
    } finally {
      approvedMemoryInFlight = false;
    }
  }

  async function loadMoreApprovedMemories(cursor) {
    if (!cursor || approvedMemoryInFlight || !clawApprovedList) return;
    approvedMemoryInFlight = true;
    const more = document.getElementById("clawApprovedMore");
    if (more) more.disabled = true;
    try {
      const response = await fetch(
        `/api/claw/memory?cursor=${encodeURIComponent(cursor)}`,
        { headers: { "Accept": "application/json" }, cache: "no-store" },
      );
      const data = await response.json().catch(() => null);
      if (response.status === 400) {
        // Expired or forged cursor: stop, remove the button and show a notice.
        if (more) more.remove();
        setApprovedMemoryStatus(uiT("projects-more-stale"), "error");
        return;
      }
      if (!response.ok || !data || !Array.isArray(data.memories)) return;
      data.memories.forEach((memory) => {
        if (!memory || typeof memory.memory_id !== "string") return;
        clawApprovedList.appendChild(renderApprovedMemoryCard(memory));
      });
      const next = typeof data.next_cursor === "string" ? data.next_cursor : "";
      if (more && next) {
        more.dataset.cursor = next;
        more.disabled = false;
      } else if (more) {
        more.remove();
      }
    } finally {
      approvedMemoryInFlight = false;
    }
  }

  async function loadApprovedMemoryDetail(memoryId) {
    if (!clawApprovedMemory || approvedMemoryInFlight) return;
    approvedMemoryInFlight = true;
    setApprovedMemoryStatus("", "");
    if (clawApprovedLoading) clawApprovedLoading.hidden = false;
    if (clawApprovedList) clawApprovedList.hidden = true;
    if (clawApprovedEmpty) clawApprovedEmpty.hidden = true;
    try {
      const response = await fetch(`/api/claw/memory/${encodeURIComponent(memoryId)}`, { headers: { "Accept": "application/json" }, cache: "no-store" });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || !data.memory) {
        throw mappedUiError(approvedMemoryErrorMessage(data, response), data);
      }
      if (clawApprovedLoading) clawApprovedLoading.hidden = true;
      if (clawApprovedList) clawApprovedList.hidden = false;
      renderApprovedMemoryDetail(data.memory);
      // #4488 Phase A follow-up: a detail opened from inside the panel must be
      // visible (run-history focus parity — open the disclosure first).
      if (clawApprovedDisclosure) clawApprovedDisclosure.open = true;
    } catch (error) {
      if (clawApprovedLoading) clawApprovedLoading.hidden = true;
      setApprovedMemoryStatus(safeLocalUiMessage(error, clawT("claw-memory-error-generic")), "error", error?.code);
    } finally {
      approvedMemoryInFlight = false;
    }
  }

  function syncApprovedMemoryVisibility() {
    if (!clawApprovedMemory) return;
    // Owner-authenticated surface only: anonymous Phase A flow is unchanged.
    const onLanding = clawWorkspace?.dataset.view === "general"
      && !emptyState.hidden;
    const inActiveChat = shell.dataset.state === "chat" && emptyState.hidden;
    const show = authState.authenticated === true
      && (shell.dataset.state === "claw" || inActiveChat)
      && !onLanding;
    clawApprovedMemory.hidden = !show;
    if (clawApprovedDisclosure) clawApprovedDisclosure.hidden = !show;
    if (show) loadApprovedMemoryList();
  }

  if (clawApprovedRefresh) {
    clawApprovedRefresh.addEventListener("click", () => loadApprovedMemoryList());
  }

  // Claw recent-run presentation (#2317 owner-scoped run history route).
  // Presentation only: the browser renders what GET /api/claw/runs already
  // exposes to the signed-in owner and never mints its own run/history truth.
  const clawRunHistory = document.getElementById("clawRunHistory");
  // #4488 Phase A: recent runs are progressive disclosure on the Claw entry.
  const clawRunHistoryDisclosure = document.getElementById("clawRunHistoryDisclosure");
  const clawRunHistoryRefresh = document.getElementById("clawRunHistoryRefresh");
  const clawRunHistoryFilter = document.getElementById("clawRunHistoryFilter");
  const clawRunHistoryExpand = document.getElementById("clawRunHistoryExpand");
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

  // Unknown status tokens stay raw rather than being invented, so presentation
  // can never claim a completion the server did not report.
  function clawRunStatusLabel(status) {
    const raw = String(status || "");
    const key = `claw-runs-status-${raw}`;
    const text = uiT(key);
    // Deliberately raw for an unknown run token: #3933 and the run-history UI
    // contract forbid the client deriving a run status, so an invented Korean
    // label here would be a second kind of untruth.
    return text === key ? raw : text;
  }

  function renderClawRunCard(run) {
    // L6: the meta line printed the raw ISO-8601 UTC instant the server stored
    // ("2026-09-19T01:00:00Z") straight at the reader. Show the same instant in
    // the page's own language and zone instead, and keep the exact stored value
    // in the element's title so nothing is hidden. A value the browser cannot
    // parse is shown exactly as the server sent it rather than as a guess.
    const instantLanguage = typeof document?.documentElement?.lang === "string"
      && document.documentElement.lang.toLowerCase().startsWith("en") ? "en" : "ko";
    const readableClawInstant = (value) => {
      if (typeof value !== "string" || !value) return "";
      const parsed = new Date(value);
      if (Number.isNaN(parsed.getTime())) return value;
      try {
        return new Intl.DateTimeFormat(instantLanguage, {
          dateStyle: "medium", timeStyle: "short",
        }).format(parsed);
      } catch (_) {
        return value;
      }
    };
    // L2 result-file card: the kind shown on a completed run's file is derived
    // ONLY from the server-verified media_type the owner-scoped run projection
    // already carries. A filename extension is never used to invent a type, and
    // an absent or unregistered media type renders no chip rather than a guess.
    // The map is closed, so a hostile media type can only fail to match.
    const artifactKindMap = Object.freeze({
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "XLSX",
      "application/vnd.ms-excel": "XLS",
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "DOCX",
      "application/msword": "DOC",
      "application/vnd.openxmlformats-officedocument.presentationml.presentation": "PPTX",
      "application/pdf": "PDF",
      "text/csv": "CSV",
      "text/plain": "TXT",
      "application/zip": "ZIP",
      "image/png": "PNG",
      "image/jpeg": "JPG",
      "image/webp": "WEBP",
    });
    const artifactKindOf = (mediaType) => {
      if (typeof mediaType !== "string") return "";
      const normalized = mediaType.trim().toLowerCase();
      // Object prototype members such as "constructor" and "__proto__"
      // are not registered media types and must never produce a file chip.
      return Object.hasOwn(artifactKindMap, normalized) ? artifactKindMap[normalized] : "";
    };
    const card = document.createElement("div");
    card.className = "claw-run-card";
    card.dataset.runId = typeof run.run_id === "string" ? run.run_id : "";
    // Visual emphasis follows only the canonical server status. Unknown states
    // retain neutral styling and their raw label; they are never completed.
    const knownRunStates = ["completed", "waiting_approval", "failed", "cancelled"];
    if (knownRunStates.includes(run.status)) card.dataset.runState = run.status;

    const head = document.createElement("div");
    head.className = "claw-run-card-head";
    const title = document.createElement("strong");
    title.className = "claw-run-card-title";
    title.textContent = typeof run.title === "string" ? run.title : "";
    const badge = document.createElement("span");
    badge.className = "claw-run-card-badge";
    badge.textContent = clawRunStatusLabel(run.status);
    head.append(title, badge);

    const meta = document.createElement("div");
    meta.className = "claw-run-card-meta";
    const createdAt = typeof run.created_at === "string" ? run.created_at : "";
    meta.textContent = [run.channel, run.action, readableClawInstant(createdAt)]
      .map((value) => (typeof value === "string" ? value : ""))
      .filter(Boolean)
      .join(" · ");
    // The exact instant the server stored stays available even though the
    // visible text is localized, so nothing about the record is lost.
    if (createdAt) meta.setAttribute("title", createdAt);

    const summary = document.createElement("p");
    summary.className = "claw-run-card-summary";
    summary.textContent = typeof run.result_summary === "string" ? run.result_summary : "";

    card.append(head, meta, summary);
    if (["waiting_approval", "failed", "cancelled"].includes(run.status)) {
      const nextStep = document.createElement("p");
      nextStep.className = "claw-run-card-nextstep";
      nextStep.setAttribute("role", "note");
      nextStep.textContent = clawT(`claw-runs-next-${run.status}`);
      card.appendChild(nextStep);
    }

    // Canonical session reopen (#2916): the action exists only when the server
    // projected a validated session handle. Created before the artifact block
    // (run-card static slice) and appended after it, so document action and
    // session action stay separate single-purpose controls that both reuse
    // existing owners instead of minting new authority.
    const sessionConversationId = run.session && typeof run.session.conversation_id === "string" && run.session.conversation_id
      ? run.session.conversation_id
      : null;
    let sessionBtn = null;
    if (sessionConversationId) {
      sessionBtn = document.createElement("button");
      sessionBtn.type = "button";
      sessionBtn.className = "claw-run-card-download claw-run-card-session";
      sessionBtn.textContent = clawT("claw-runs-open-session");
      sessionBtn.addEventListener("click", () => {
        openSavedConversation(sessionConversationId);
      });
    }

    const artifact = run.artifact && typeof run.artifact.document_id === "string" ? run.artifact : null;
    if (artifact) {
      const artifactRow = document.createElement("div");
      artifactRow.className = "claw-run-card-artifact";
      // L2: the file's own identity is grouped so a type chip can sit beside the
      // name. Grouping keeps the row's two-element shape (identity + one action)
      // and lets a long filename shrink instead of pushing the action out.
      const fileGroup = document.createElement("span");
      fileGroup.className = "claw-run-card-file";
      const artifactKind = artifactKindOf(artifact.media_type);
      if (artifactKind) {
        const kindChip = document.createElement("span");
        kindChip.className = "claw-run-card-kind";
        kindChip.textContent = artifactKind;
        kindChip.setAttribute("aria-label", clawT("claw-runs-kind-aria", { kind: artifactKind }));
        fileGroup.appendChild(kindChip);
      }
      const filename = document.createElement("span");
      filename.className = "claw-run-card-filename";
      filename.textContent = typeof artifact.filename === "string" ? artifact.filename : "";
      fileGroup.appendChild(filename);
      const downloadBtn = document.createElement("button");
      downloadBtn.type = "button";
      downloadBtn.className = "claw-run-card-download";
      downloadBtn.textContent = clawT("claw-runs-download");
      downloadBtn.addEventListener("click", () => {
        // Reuses the existing bounded artifact route through its single owner.
        if (artifact.document_id) downloadClawArtifact(artifact.document_id, artifact.filename || "");
      });
      artifactRow.append(fileGroup, downloadBtn);
      // L2: one verified-preview decision, reused by the note and the controller.
      const previewable = Boolean(window.PadiemClawPdfPreview?.validHistoricalArtifact?.(artifact));
      // #3935: a history artifact reference does not make a failed, cancelled,
      // approval-paused or unknown run completed. Keep its original badge and
      // existing click-to-check download; never auto-retry or claim delivery.
      if (run.status !== "completed") {
        const caveat = document.createElement("p");
        caveat.className = "claw-run-card-partial-note";
        caveat.setAttribute("role", "note");
        caveat.textContent = clawT("claw-runs-artifact-unverified");
        artifactRow.appendChild(caveat);
      }
      // L2: when no verified preview exists for this file, say so plainly so the
      // single download action is never read as a preview affordance.
      if (!previewable) {
        const downloadOnly = document.createElement("p");
        downloadOnly.className = "claw-run-card-download-only";
        downloadOnly.setAttribute("role", "note");
        downloadOnly.textContent = clawT("claw-runs-download-only");
        fileGroup.appendChild(downloadOnly);
      }
      // #3932: old owner-scoped run receipts lack byte_length. Display a
      // truthful click-to-check PDF action, then use the existing authenticated
      // 10MiB PDF byte route. Never preview DOCX/XLSX or inferred filenames.
      if (previewable) {
        const viewer = window.PadiemClawPdfPreview.create({
          mount: artifactRow,
          onError: (message) => setClawRunHistoryStatus(message),
        });
        if (viewer?.setHistorical?.(artifact)) clawRunHistoryPdfControllers.add(viewer);
        else viewer?.destroy?.();
      }
      card.appendChild(artifactRow);
    }
    if (sessionBtn) card.appendChild(sessionBtn);
    if (run.status === "waiting_approval" && typeof run.run_id === "string" && run.run_id) {
      const approvalActions = document.createElement("div");
      approvalActions.className = "claw-approval-actions claw-run-approval-actions";
      approvalActions.setAttribute("role", "group");
      approvalActions.setAttribute("aria-label", clawT("claw-approval-actions-aria"));
      renderClawApprovalControls(approvalActions, run.run_id, async () => {
        await loadClawRunHistory();
      });
      card.appendChild(approvalActions);
    }
    return card;
  }

  function fetchClawRunHistory(...a) { return historyModule().fetchClawRunHistory(...a); }

  function loadClawRunHistory(...a) { return historyModule().loadClawRunHistory(...a); }

  function syncClawRunHistoryVisibility(...a) { return historyModule().syncClawRunHistoryVisibility(...a); }

  window.PadiemChatMemoryReview = Object.freeze({
    render: renderMemoryProposalReview,
    sync: () => {
      syncApprovedMemoryVisibility();
      syncClawRunHistoryVisibility();
    },
  });
  if (clawRunHistoryFilter) {
    clawRunHistoryFilter.addEventListener("click", () => {
      const next = window.__padiemClawRunHistoryIncludeGeneral !== true;
      window.__padiemClawRunHistoryIncludeGeneral = next;
      clawRunHistoryFilter.dataset.runFilter = next ? "all" : "tools";
      clawRunHistoryFilter.setAttribute("aria-pressed", next ? "true" : "false");
      clawRunHistoryFilter.setAttribute("data-locale-key", next ? "claw-runs-filter-all" : "claw-runs-filter-tools");
      clawRunHistoryFilter.textContent = uiT(next ? "claw-runs-filter-all" : "claw-runs-filter-tools");
      void loadClawRunHistory({ force: true });
    });
  }
  if (clawRunHistoryRefresh) {
    // A person asked for the current list, so this read is not served from the
    // short window.
    clawRunHistoryRefresh.addEventListener("click", () => loadClawRunHistory({ force: true }));
  }
  if (clawRunHistoryExpand) {
    clawRunHistoryExpand.addEventListener("click", () => {
      if (clawRunHistoryInFlight || clawRunHistoryLimit !== 10 ||
          authState.authenticated !== true || clawRunHistory.hidden) return;
      clawRunHistoryLimit = 30;
      clawRunHistoryExpand.hidden = true;
      void loadClawRunHistory({ force: true });
    });
  }

  // ---------------------------------------------------------------------------
  // #3084 — Claw "Connect this computer" handoff panel.
  //
  // This is presentation only. It renders a projection that some upstream
  // authority already decided, and it holds none of the following:
  //   - pairing token minting/parsing/storage
  //   - a device-session store
  //   - a transport client (no fetch/WebSocket/polling to any broker)
  //   - task admission or approval decisions
  // The CTA therefore does NOT navigate or open a deep link here. It emits a
  // custom event carrying the opaque handoff value; the #3080 adapter (not yet
  // in this branch) is the only thing allowed to act on it.
  // ---------------------------------------------------------------------------
  const localHandoff = window.PadiemClawLocalHandoff;
  const localHandoffPanel = document.getElementById("clawLocalHandoff");
  const localHandoffRefs = localHandoffPanel
    ? {
        panel: localHandoffPanel,
        title: document.getElementById("clawLocalTitle"),
        body: document.getElementById("clawLocalBody"),
        state: document.getElementById("clawLocalState"),
        cta: document.getElementById("clawLocalCta"),
        installNote: document.getElementById("clawLocalInstallNote"),
        openNote: document.getElementById("clawLocalOpenNote"),
        identity: document.getElementById("clawLocalIdentity"),
        approval: document.getElementById("clawLocalApproval"),
        approvalTitle: document.getElementById("clawLocalApprovalTitle"),
        approvalBody: document.getElementById("clawLocalApprovalBody"),
        status: document.getElementById("clawLocalStatus"),
        statusTitle: document.getElementById("clawLocalStatusTitle"),
        statusBody: document.getElementById("clawLocalStatusBody"),
        result: document.getElementById("clawLocalResult"),
        resultTitle: document.getElementById("clawLocalResultTitle"),
        resultBody: document.getElementById("clawLocalResultBody"),
        evidence: document.getElementById("clawLocalEvidence"),
        evidenceTitle: document.getElementById("clawLocalEvidenceTitle"),
        evidenceList: document.getElementById("clawLocalEvidenceList"),
      }
    : null;
  const localHandoffCta = localHandoffRefs ? localHandoffRefs.cta : null;

  let localHandoffViewModel = null;

  function projectLocalHandoff(projection) {
    if (!localHandoff || !localHandoffRefs) return null;
    const model = localHandoff.deriveHandoffViewModel(projection || {});
    localHandoffViewModel = model;
    localHandoff.projectHandoffPanel(localHandoffRefs, model, window.__padiemLocale?.getCurrent?.() || "ko");
    return model;
  }

  if (localHandoffCta) {
    localHandoffCta.addEventListener("click", () => {
      const model = localHandoffViewModel;
      // Never act unless the projection is genuinely usable. This is the
      // false-connected guard at the interaction layer, not just the view.
      if (!model || !model.canProceed) return;
      window.dispatchEvent(
        new CustomEvent("padiem:claw-local-connect-requested", {
          detail: {
            handoffValue: model.handoff.value,
            conversationId: model.identity.conversationId,
            runId: model.identity.runId,
            taskId: model.identity.taskId,
          },
        }),
      );
    });
  }

  // Re-render on locale change so KO/EN copy stays truthful.
  window.addEventListener("padiem:localechange", () => {
    if (!localHandoffViewModel || !localHandoffRefs) return;
    localHandoff.projectHandoffPanel(
      localHandoffRefs,
      localHandoffViewModel,
      window.__padiemLocale?.getCurrent?.() || "ko",
    );
  });

  // Narrow injection seam for the #3080 contract. Until that authority lands,
  // the deterministic fixtures are the only source. No network call exists here.
  window.__padiemClawLocalHandoff = Object.freeze({
    contractVersion: localHandoff?.CONTRACT_VERSION || null,
    project: projectLocalHandoff,
    getViewModel: () => localHandoffViewModel,
    fixtures: localHandoff?.FIXTURES || null,
    // #3094: the live conversation id, so the guarded adapter correlates the
    // projection it fetches with the conversation the user is actually in.
    // Read-only: this exposes no pairing, session or transport authority.
    getConversationId: () => window.PadiemChatConversationState?.getConversationId?.() || null,
  });
  // Restore the Automation surface only after all handlers are registered.
  // It remains read-only for signed-out sessions through openClawAutomation().
  // #4862: restore Claw the same way. An unknown or tampered fragment matches
  // neither route, so the shell keeps its default Chat home.
  if (window.location.hash === AUTOMATION_ROUTE_HASH) openClawAutomation();
  else if (window.location.hash === CLAW_ROUTE_HASH) openClawWorkspace();
  else if (window.location.hash === CONNECTORS_ROUTE_HASH) openConnectorsView();
  else if (window.location.hash === ADVANCED_SETTINGS_ROUTE_HASH) openAdvancedSettingsView();
  // Calendar, Library and Meeting are reachable only through the menu, so a
  // shared link used to land on Chat with whatever fragment the previous screen
  // left behind. Each of the three now names itself, and the screen that owns
  // the surface opens it: Meeting is driven here, Calendar and Library answer
  // the published request from their own modules.
  const requestedRouteHash = String(window.location.hash || "");
  if (requestedRouteHash === CALENDAR_ROUTE_HASH
    || requestedRouteHash === LIBRARY_ROUTE_HASH
    || requestedRouteHash === MEETING_ROUTE_HASH) {
    const restoreShellRouteFromHash = () => {
      if (requestedRouteHash === MEETING_ROUTE_HASH) {
        window.dispatchEvent(new CustomEvent("padiem:meeting-open"));
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
