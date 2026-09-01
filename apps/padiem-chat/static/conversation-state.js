(() => {
  "use strict";

  const MAX_MESSAGES = 20;
  let messages = [];
  let conversationId = null;
  let skill = "auto";

  function tail(items) {
    return items.slice(-MAX_MESSAGES);
  }

  function reset() {
    messages = [];
    conversationId = null;
    skill = "auto";
  }

  function appendMessage(message) {
    messages = tail(messages.concat([message]));
  }

  function outboundWithUser(content) {
    return tail(messages.concat([{ role: "user", content }]));
  }

  function commitAssistant(outboundMessages, content) {
    messages = tail(outboundMessages.concat([{ role: "assistant", content }]));
  }

  function getConversationId() {
    return conversationId;
  }

  function setConversationId(value) {
    conversationId = value;
  }

  function getSkill() {
    return skill;
  }

  function setSkill(value) {
    skill = value;
  }

  window.PadiemChatConversationState = Object.freeze({
    reset,
    appendMessage,
    outboundWithUser,
    commitAssistant,
    getConversationId,
    setConversationId,
    getSkill,
    setSkill,
  });
})();
