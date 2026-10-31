(() => {
  "use strict";

  // #2505 owner decision (2026-10-21): Chat and Claw are two screens of ONE AI
  // product, so they share ONE conversation. A thread started on either screen
  // keeps its turns and its conversation id when the other screen is opened, so
  // the same stored conversation is continued instead of splitting in two.
  //
  // The server has always stored both lanes in the single `b62-chat` product
  // scope, so this store is the browser side of that same record — no second
  // thread was ever persisted, only a second browser slot.
  //
  // What stays per turn is the LANE, not the thread: the product named at submit
  // time still decides which route answers, which model roster applies and which
  // tools are available. Nothing here reads the DOM, the network or a model: it
  // is the browser-side turn store only.
  const PRODUCT_IDS = Object.freeze(["chat", "claw"]);
  const conversation = { messages: [], conversationId: null, skill: "auto" };
  let activeProduct = "chat";

  function known(product) {
    return PRODUCT_IDS.includes(product) ? product : null;
  }

  // The active product is the lane the next submit belongs to, not a thread.
  function setProduct(product) {
    const id = known(product);
    if (id) activeProduct = id;
    return activeProduct;
  }
  function getProduct() {
    return activeProduct;
  }

  // One conversation, so every reset clears the same thread. The product
  // argument is still accepted: a caller that resets "its" side clears the one
  // conversation both screens show.
  function resetProduct() {
    conversation.messages = [];
    conversation.conversationId = null;
    conversation.skill = "auto";
  }
  function reset() {
    resetProduct();
  }
  function resetAll() {
    resetProduct();
  }

  function appendMessage(message) {
    conversation.messages = conversation.messages.concat([message]);
  }

  function outboundWithUser(content) {
    return conversation.messages.concat([{ role: "user", content }]);
  }

  function commitAssistant(outboundMessages, content) {
    conversation.messages = outboundMessages.concat([{ role: "assistant", content }]);
  }

  function getConversationId() {
    return conversation.conversationId;
  }

  function setConversationId(value) {
    conversation.conversationId = value;
  }

  function getSkill() {
    return conversation.skill;
  }

  function setSkill(value) {
    conversation.skill = value;
  }

  window.PadiemChatConversationState = Object.freeze({
    reset,
    resetAll,
    resetProduct,
    setProduct,
    getProduct,
    appendMessage,
    outboundWithUser,
    commitAssistant,
    getConversationId,
    setConversationId,
    getSkill,
    setSkill,
  });
})();
