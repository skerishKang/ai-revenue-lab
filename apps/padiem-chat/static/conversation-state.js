(() => {
  "use strict";

  let messages = [];
  let conversationId = null;
  let skill = "auto";

  function reset() {
    messages = [];
    conversationId = null;
    skill = "auto";
  }

  function appendMessage(message) {
    messages = messages.concat([message]);
  }

  function outboundWithUser(content) {
    return messages.concat([{ role: "user", content }]);
  }

  function commitAssistant(outboundMessages, content) {
    messages = outboundMessages.concat([{ role: "assistant", content }]);
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
