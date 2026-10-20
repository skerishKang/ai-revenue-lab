(() => {
  "use strict";

  // Chat/Claw separation: Chat(B62) and Claw(B54) share one conversation panel, but they
  // never share one conversation. Each product owns its own turns, its own
  // conversation id and its own skill, so a Claw request can never carry the
  // Chat conversation id and a Chat request can never carry the Claw one.
  //
  // The plain API keeps operating on the active product (the product whose
  // request is in flight, otherwise the product the panel currently shows),
  // and any caller may also name the product explicitly. Nothing here reads
  // the DOM, the network or a model: it is the browser-side turn store only.
  const PRODUCT_IDS = Object.freeze(["chat", "claw"]);
  const slots = new Map();
  let activeProduct = "chat";

  function known(product) {
    return PRODUCT_IDS.includes(product) ? product : null;
  }
  function slot(product) {
    const id = known(product) || activeProduct;
    if (!slots.has(id)) slots.set(id, { messages: [], conversationId: null, skill: "auto" });
    return slots.get(id);
  }

  function setProduct(product) {
    const id = known(product);
    if (id) activeProduct = id;
    return activeProduct;
  }
  function getProduct() {
    return activeProduct;
  }

  // One product's own reset. The other product's conversation is untouched.
  function resetProduct(product) {
    const target = slot(product);
    target.messages = [];
    target.conversationId = null;
    target.skill = "auto";
  }
  // A new conversation for the active product. The other product keeps its
  // own conversation and is restored when the user returns to it.
  function reset() {
    resetProduct(activeProduct);
  }
  // Every product starts empty again.
  function resetAll() {
    PRODUCT_IDS.forEach((id) => resetProduct(id));
  }

  function appendMessage(message, product) {
    const target = slot(product);
    target.messages = target.messages.concat([message]);
  }

  function outboundWithUser(content, product) {
    return slot(product).messages.concat([{ role: "user", content }]);
  }

  function commitAssistant(outboundMessages, content, product) {
    const target = slot(product);
    target.messages = outboundMessages.concat([{ role: "assistant", content }]);
  }

  function getConversationId(product) {
    return slot(product).conversationId;
  }

  function setConversationId(value, product) {
    slot(product).conversationId = value;
  }

  function getSkill(product) {
    return slot(product).skill;
  }

  function setSkill(value, product) {
    slot(product).skill = value;
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
